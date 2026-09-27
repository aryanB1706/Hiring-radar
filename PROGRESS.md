# Progress

| Step | Name | Status | Summary |
|------|------|--------|---------|
| 01 | Skeleton (`specs/01-skeleton.md`) | Done | Clean FastAPI skeleton, PostgreSQL 16 Compose setup, structlog request-id tracking, /api/health with DB ping and 503 fallback, ruff and pytest passing. |
| 02 | Data model (`specs/02-schema.md`) | Pending | Tables, Alembic migrations, DB models. |
| 03 | LLM gateway (`specs/03-llm-gateway.md`) | Pending | Gemini client factory, rate limiter, retries, call logging. |
| 04 | Collectors + ingestion (`specs/04-collectors.md`) | Pending | HN Algolia, Reddit PRAW, manual capture, idempotent ingestion. |
| 05 | Classifier (`specs/05-classifier.md`) | Pending | Structured Pydantic output, quotes, confidence. |
| 06 | Classifier eval harness (`specs/06-eval-classifier.md`) | Pending | Eval dataset, metrics, precision/recall. |
| 07 | Qualification agent loop (`specs/07-agent-loop.md`) | Pending | LangGraph tool loop, budgets, scam score, needs_human. |
| 08 | Agent tools (`specs/08-agent-tools.md`) | Pending | SSRF protection, robots.txt, tool schemas. |
| 09 | External agent surface (`specs/09-agent-surface.md`) | Pending | REST + official MCP SDK, auth, approval gate, audit log. |
| 10 | Human feed & review UI (`specs/10-ui.md`) | Pending | Jinja + HTMX feed, approvals, traces. |

## Notes
- Stack uses Python 3.12, FastAPI, SQLAlchemy 2.x, psycopg v3, PostgreSQL 16 (plain, no pgvector).
- Host PostgreSQL port mapped to 5434 by default (`POSTGRES_PORT=5434`) to prevent port conflicts with local services.
- Test suite verified with `pytest` (2 passed). Code verified with `ruff`.
