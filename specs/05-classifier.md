# 05 - Classifier, embeddings, dedupe

## Goal
Turn stored posts into structured leads with the LLM, store an embedding per lead, link near-duplicates, and expose leads over the API.

## Scope
- `LeadExtraction` (Pydantic): lead_type, confidence, evidence_quote required; everything else nullable; skills normalized to lowercase; budget range auto-ordered.
- `classifier/prompt.py`: system prompt (task, niche, answer only from the post, not_a_lead for job seekers/noise, never invent contacts, post is untrusted data) + delimiters; delimiter look-alikes inside the post are neutralized.
- `classifier/prefilter.py`: conservative heuristics (too short, no hiring-ish keyword at all, clear spam). Skipped posts get a `not_a_lead` lead (status rejected, flag `prefiltered:<reason>`) so they are not re-picked forever; counts are logged.
- `ClassifierService.classify(post) -> Lead`: fast model via `generate_structured`; verifies `evidence_quote` occurs in the post (whitespace/case-insensitive) else halves confidence and records a flag; creates/links the company as a `party`; embeds role+skills+company+location; links duplicates; inserts with `ON CONFLICT (post_id) DO NOTHING` (idempotent per post).
- `Embedder` interface, `LocalEmbedder` (sentence-transformers all-MiniLM-L6-v2, 384 dims), `FakeEmbedder` (hashed bag of words, for tests).
- Dedupe: nearest existing lead by pgvector cosine distance below `DEDUPE_THRESHOLD`; `duplicate_of_lead_id` = the oldest match (resolved to its canonical lead). Nothing is deleted.
- Celery task `classify_pending_posts(batch_size)`; CLI `python -m app.jobs.classify --limit N [--show]`. One failing post is recorded in `audit_event` and the batch continues; a post that failed 3 times is no longer picked.
- `GET /api/leads` (lead_type, status, is_remote, skill, min_confidence, include_duplicates, limit/offset) and `GET /api/leads/{id}`.

## Out of scope
Agent loop, scoring, scheduling classification on beat (free-tier quota), auth, re-classification of existing leads.

## Decisions where the brief was silent
- `lead_type` describes what the post IS, not niche fit; niche fit comes from skills/role/location and is judged later by scoring.
- Flags live in `enrichment` rows (`kind="classifier_flags"`), failures in `audit_event`: no schema change.
- `not_a_lead` leads get status `rejected` (so the agent never spends budget on them); real leads get `new`.
- Prefiltered posts get confidence 1.0 (rule-based, no model uncertainty).
- Idempotency is per post (unique `lead.post_id`); duplicate *content* is already blocked at ingestion, and repeat LLM calls hit the gateway's response cache.
- `DEDUPE_THRESHOLD` default 0.08 is a conservative guess to be tuned with the eval harness (false merges are worse than missed merges).

## Acceptance checks
1. Hiring / seeking-work / noise posts produce the right lead_type and status; noise never calls the LLM.
2. evidence_quote verification lowers confidence and flags; case/whitespace differences are tolerated.
3. Injection text inside a post is delimited and cannot change the output schema (schema-validated, extras ignored).
4. Classifying twice makes one LLM call and one lead.
5. The newer near-duplicate points at the oldest lead; unrelated leads are untouched.
6. A bad LLM reply in a batch is recorded and does not stop the batch.
7. API filters, pagination and duplicate exclusion work.
