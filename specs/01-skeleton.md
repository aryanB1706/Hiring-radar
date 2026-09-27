# Step 01: Project Skeleton

## Goal
Establish a clean, minimal, runnable skeleton for Hiring Radar with a FastAPI application factory, PostgreSQL connectivity ping, structlog-based structured logging with request ID tracking, containerized development environment via Docker Compose, and local developer tooling (Makefile, ruff, pytest).

## Scope
1. **Directory Structure**:
   - `backend/app/` (`api/`, `core/`, `db/`) with `__init__.py` markers.
   - `backend/tests/` with `conftest.py` and test suites.
   - `specs/` for step specifications.
   - `docs/adr/` for architecture decision records.
2. **Dependency Management**:
   - `backend/pyproject.toml` with pinned dependencies: `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `psycopg` (v3 with binary), `structlog`, `httpx`, `pytest`, `pytest-asyncio`, `ruff`.
3. **Configuration**:
   - `app/core/config.py`: `Settings` class (`pydantic-settings`) reading `APP_ENV`, `DATABASE_URL`, and `LOG_LEVEL`.
   - `.env.example` documenting all configuration keys with safe defaults.
4. **Structured Logging**:
   - `app/core/logging.py`: Configures `structlog` (JSON output for `production`, colorized readable console for `development`/`test`).
   - Request ID middleware binding `request_id` to structlog context per HTTP request and returning `X-Request-ID` header.
5. **Database Session & Ping**:
   - `app/db/session.py`: SQLAlchemy engine and session factory with a lightweight ping function (`SELECT 1`).
6. **Health Endpoint & App Factory**:
   - `app/api/health.py`: `GET /api/health` returning `{ "status": "ok", "db": "connected" }` (200) or `{ "status": "unhealthy", "db": "disconnected" }` (503) if DB is unreachable.
   - `app/main.py`: `create_app()` factory assembling middleware, state, and routers.
7. **Containers & Dev Setup**:
   - `docker-compose.yml`: `postgres` (postgres:16 with pg_isready healthcheck and named volume) and `api` (built from `backend/Dockerfile` with non-root user, hot-reload).
   - `backend/Dockerfile`: Multi-stage / lean `python:3.12-slim` image running as non-root user `appuser`.
   - `Makefile`: Targets `up`, `down`, `logs`, `test`, `lint`, `fmt`.
   - `.gitignore`: Excludes caches, venvs, secrets, logs.
   - `README.md`: Basic project introduction and run instructions.
8. **Testing & CI**:
   - `backend/tests/test_health.py`: Test `GET /api/health` with DB check overridden (success and 503 failure paths).
   - `.github/workflows/ci.yml`: GitHub Actions running ruff and pytest on push and pull requests.
9. **Tracking**:
   - `PROGRESS.md`: Tracking step completion and status.

## Out of Scope
- Database ORM models, tables, and Alembic migrations (deferred to Step 02).
- LLM gateway, LangChain, LangGraph, prompt templates.
- Collectors, ingestion jobs, APScheduler tasks.
- Vector search, pgvector, Redis, Celery.

## Acceptance Checks
1. `pytest` executes and passes all tests in `backend/tests/`.
2. `ruff check .` and `ruff format --check .` succeed with no errors.
3. `GET /api/health` returns HTTP 200 with `{"status": "ok", "db": "connected"}` when the database is available.
4. `GET /api/health` returns HTTP 503 with `{"status": "unhealthy", "db": "disconnected"}` when the database ping fails.
5. `docker compose config` validates without errors.
6. `.env.example` contains all variables and no sensitive values are committed.
