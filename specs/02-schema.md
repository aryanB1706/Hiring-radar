# 02 - Data model

## Goal
The full relational schema (SQLAlchemy 2.x models + one Alembic migration), a session factory/dependency, and DB tests against the real Postgres.

## Scope
- 12 tables from the brief: source, post, party, lead, enrichment, agent_identity, agent_run, agent_step, approval, audit_event, feedback, llm_call_log.
- UUID primary keys (`gen_random_uuid()` server default), snake_case, timestamptz. `created_at`/`updated_at` on source, post, party, lead; `created_at` only on the other tables that the brief lists it for.
- Enums are `VARCHAR` + named CHECK constraints (no native PG enums, so downgrade is clean and adding a value is a one-line constraint change).
- One migration `initial_schema`: `CREATE EXTENSION vector`, tables, indexes, append-only trigger on `audit_event` (UPDATE, DELETE and TRUNCATE raise).
- `app/db/session.py`: `async_sessionmaker` factory + `get_session` FastAPI dependency (no auto-commit; callers commit).
- Tests in a rolled-back transaction per test; the test DB is `<DB>_test`, dropped/recreated and migrated once per run.
- README "Data model" with a Mermaid ER diagram.

## Decisions made where the brief was silent
- ON DELETE: source -> post RESTRICT; post -> lead, lead -> enrichment/agent_run/feedback, agent_run -> agent_step CASCADE; lead.party_id and lead.duplicate_of_lead_id SET NULL; agent_identity -> agent_run/approval RESTRICT; `audit_event` has no FKs (ids stored as text) so it outlives anything.
- `approval.decided_by` is free text (there is no human-user table yet).
- `agent_run.status` allowed values: running, succeeded, failed, needs_human, budget_exceeded.
- `lead.lead_type`, `confidence`, `classified_at` are NOT NULL (a lead row is created after classification).
- Extra constraints: UNIQUE(source.kind, source.name), UNIQUE(agent_step.agent_run_id, step_no), confidence/scam_risk within 0..1, budget_min <= budget_max, approval decided_at set iff not pending.

## Out of scope
Ingestion logic, LLM code, vector (HNSW/IVFFlat) indexes, seed data, auth.

## Acceptance checks
1. `alembic upgrade head`, `alembic downgrade base`, `alembic upgrade head` all succeed; models and migration produce no autogenerate diff.
2. UNIQUE(source_id, external_id) enforced.
3. UPDATE/DELETE/TRUNCATE on `audit_event` raise; INSERT works.
4. FK behaviours above are tested; invalid enum values are rejected by the database.
5. pgvector insert + nearest-neighbour query works.
6. `pytest` and `ruff` pass.
