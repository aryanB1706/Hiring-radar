# 04 - Collectors and idempotent ingestion

## Goal
Pull posts from allowed sources into PostgreSQL, safely repeatable, plus user-initiated capture.

## Scope
- `SourceAdapter` + `RawPost`; adapters: Hacker News (Algolia: latest hiring / seeking work / freelance thread, top-level comments), Reddit (PRAW, read-only), RSS/Atom (feedparser).
- Disabled `LinkedInAdapter`/`InstagramAdapter` (raise `DisabledSourceError` -> ADR 0001).
- `PoliteHttpClient`: User-Agent from env, timeouts, per-host delay, robots.txt check (`check_robots=True`, used for RSS feeds).
- `IngestService`: strip/normalize text, sha256 content hash, `INSERT .. ON CONFLICT DO NOTHING`, cross-source duplicate skip; counts `fetched/inserted/skipped_duplicate` (+ `skipped_empty`). Caller owns the session; commits every 100 posts.
- `POST /api/captures` (JSON) and `POST /api/captures/csv` (raw CSV body `url,text[,author_handle]`; 1 MB / 500 row cap; per-row rejects reported).
- Celery: `ingest_source(source_id)`, `ingest_all_sources` (beat, every `INGEST_INTERVAL_HOURS`), worker + beat in compose. CLI `python -m app.jobs.ingest --source hn|reddit|rss|linkedin [--feed URL] [--full]`.
- Settings/.env.example: REDDIT_*, HTTP_USER_AGENT, SUBREDDITS, INGEST_INTERVAL_HOURS (+ HTTP_TIMEOUT_SECONDS, HTTP_MIN_DELAY_SECONDS).
- ADR 0001.

## Out of scope
Classification, LLM calls, auth on the capture endpoints (Stage 3), storing `RawPost.extra`, language detection.

## Decisions where the brief was silent
- CSV endpoint takes a raw `text/csv` body, not multipart (multipart needs an extra dependency, python-multipart).
- `url` is required on captures (the `post.url` column is NOT NULL); a capture's external id is the hash of its URL.
- Scheduled/CLI runs are incremental (newest stored post minus 1 day); `--full` re-reads everything. Safe either way because ingestion is idempotent.
- No storable `SourceKind` exists for Instagram, so `InstagramAdapter.kind` is None (a schema change just for a disabled skeleton is not worth it).
- Duplicate-by-content check is a SELECT then INSERT: two concurrent ingests of identical text could both insert. Acceptable now; the unique (source, external_id) constraint still guards the common case.

## Acceptance checks
1. Each adapter parses recorded fixtures (HN fixtures are real Algolia responses, trimmed; Reddit and RSS fixtures are hand-written).
2. Ingesting the same posts twice inserts 0 the second time; same text from another source is skipped.
3. Disabled adapters raise `DisabledSourceError`; the registry never returns a working adapter for them.
4. Capture endpoints validate input, strip HTML, report duplicates and bad CSV rows.
5. `python -m app.jobs.ingest --source hn` stores real posts; running it again inserts 0.
