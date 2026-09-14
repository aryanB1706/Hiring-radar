# 01 - Skeleton

## Goal
A clean, runnable project skeleton: FastAPI app, settings, logging, health check, Docker Compose, tests, CI. No product features.

## Scope
- Layout: `backend/app/{api,core,db}`, `backend/tests`, `specs/`, `docs/adr/`.
- Pinned dependencies (`requirements.txt`, `requirements-dev.txt`); tool config in `backend/pyproject.toml`.
- `app/core/config.py`: one `Settings` class (APP_ENV, DATABASE_URL, REDIS_URL, LOG_LEVEL); `.env.example`.
- `app/core/logging.py`: structlog (JSON in prod, console in dev); request id bound per request, echoed in `X-Request-ID`.
- `app/main.py`: `create_app()`; `GET /api/health` -> `{status, db, redis}`, pings both, 503 if either is down.
- `docker-compose.yml` (postgres pgvector pg16, redis, api with hot reload), `backend/Dockerfile` (non-root), `Makefile`, `.gitignore`, `README.md`.
- `tests/test_health.py` (ok path, 503 path), `.github/workflows/ci.yml`, `PROGRESS.md`.

## Out of scope
Tables, migrations, LLM code, collectors, auth, frontend.

## Acceptance checks
1. `pytest` passes without a running DB/Redis (dependencies overridden).
2. `ruff check` and `ruff format --check` pass.
3. `docker compose up` -> `curl localhost:8000/api/health` returns 200 `{"status":"ok","db":"ok","redis":"ok"}`.
4. Stopping redis or postgres makes the endpoint return 503 with the failing part marked `"down"`.
5. Every response carries an `X-Request-ID`; logs for that request include the same id.
