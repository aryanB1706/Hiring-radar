# Step 02: Data Model and Migrations

## Goal
Establish the relational data model for Hiring Radar using SQLAlchemy 2.x declarative models and Alembic migrations targeting PostgreSQL 16. Ensure idempotence, data integrity, auditability (append-only trigger), and index optimization.

## Scope
1. **Dependencies**:
   - Add `alembic==1.20.1` to `backend/pyproject.toml`.
2. **SQLAlchemy 2.x ORM Models** (`app/db/models.py`):
   - All tables use UUID primary keys (`uuid_generate_v4` or Python UUID defaults), UTC `created_at`, and `updated_at` where appropriate.
   - Tables:
     1. `source`: Platform definitions (`hn`, `reddit`, `manual_paste`, `csv_import`, `user_capture`), enabled flag, JSONB config.
     2. `post`: Raw posts tied to `source_id` with `UNIQUE(source_id, external_id)`, `content_hash`, indexes on `content_hash` and `posted_at`.
     3. `lead`: Extracted opportunities linked to `post_id` (1-to-1). Fields for `company_name`, `company_key`, `lead_type`, `skills` (ARRAY of String), `seniority`, `location`, `is_remote`, budget range, `confidence`, `evidence_quote`, `status`, `score`, `scam_risk`, `duplicate_of_lead_id` (self-referential FK). Indexes on `(status, score)`, `lead_type`, and `company_key`.
     4. `agent_identity`: Scoped agent credentials with role (`analyst`, `outreach`), hashed API keys, and scopes.
     5. `agent_run`: Execution session records per lead qualification with step, token, and USD cost tracking.
     6. `agent_step`: Granular tool invocations per run (tool input/output JSONB, latency ms, errors).
     7. `approval`: Human approval queue for risky agent actions (pending, approved, rejected, executed).
     8. `audit_event`: Immutable audit log. Enforced via a PostgreSQL trigger function that raises an exception on `UPDATE` or `DELETE`.
     9. `llm_call_log`: Telemetry for every model inference (tokens in/out, latency, cost estimate, cache status).
3. **Alembic Migration**:
   - Configure `alembic.ini` and `migrations/env.py`.
   - Initial migration containing all 9 tables, indexes, constraints, and the append-only trigger for `audit_event`.
   - Verified two-way migration: `alembic upgrade head` and `alembic downgrade base`.
4. **Session & Dependencies** (`app/db/session.py`):
   - Provide clean transactional session dependency for endpoints and tests.
5. **Testing** (`backend/tests/test_schema.py`):
   - Validate `(source_id, external_id)` uniqueness.
   - Validate `audit_event` trigger blocks `UPDATE` and `DELETE`.
   - Validate foreign key cascade/restrict constraints.
6. **Documentation**:
   - Add a Mermaid Entity-Relationship diagram in `README.md`.
   - Update `PROGRESS.md`.

## Out of Scope
- Ingestion jobs and scrapers (Step 04).
- Classifier prompt and evaluation code (Steps 05 & 06).
- LangGraph agent loop implementation (Step 07).

## Acceptance Checks
1. `alembic upgrade head` applies cleanly against PostgreSQL.
2. `alembic downgrade base` rolls back cleanly without leaving orphan tables or types.
3. `alembic upgrade head` reapplies cleanly.
4. `backend/tests/test_schema.py` passes all database constraint tests against real PostgreSQL.
5. `ruff check backend` and `ruff format --check backend` are 100% clean.
