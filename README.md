# Hiring Radar

Agent-native platform that finds hiring and freelance-gig signals on public sources, qualifies each lead with a tool-using AI agent, and provides a ranked lead feed for recruiters and agencies.

## Target Niche
Python, Backend, and GenAI developer roles, internships, and freelance gigs (India + Remote).

## Tech Stack
- **Backend**: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, psycopg v3, structlog, httpx
- **Database**: PostgreSQL 16 (plain image, no pgvector)
- **Agent Framework**: LangChain, LangGraph (with Google Gemini API on free tier)
- **Tooling**: Docker Compose, pytest, ruff, make

## Prerequisites
- Docker & Docker Compose
- Python 3.12+ (for local host development)

## Quick Start (Docker Compose)

1. Copy the example environment configuration:
   ```bash
   cp .env.example .env
   ```
2. Start the services:
   ```bash
   make up
   ```
3. Check the health endpoint:
   ```bash
   curl http://localhost:8000/api/health
   ```
4. Stop the services:
   ```bash
   make down
   ```

## Local Development

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv backend/.venv
   source backend/.venv/bin/activate
   ```
2. Install the backend package and development dependencies:
   ```bash
   cd backend && pip install -e ".[dev]"
   ```
3. Run tests and linters:
   ```bash
   make lint
   make test
   ```

## Data Model

The database is built on PostgreSQL 16 using SQLAlchemy 2.x declarative models and managed with Alembic migrations (`backend/migrations/`).

```mermaid
erDiagram
    SOURCE ||--o{ POST : "contains"
    POST ||--o| LEAD : "classified_as"
    LEAD ||--o{ LEAD : "duplicate_of"
    LEAD ||--o{ AGENT_RUN : "evaluates"
    AGENT_IDENTITY ||--o{ AGENT_RUN : "executes"
    AGENT_RUN ||--o{ AGENT_STEP : "performs"
    AGENT_IDENTITY ||--o{ APPROVAL : "requests"

    SOURCE {
        uuid id PK
        string kind
        string name
        boolean enabled
        jsonb config
    }

    POST {
        uuid id PK
        uuid source_id FK
        string external_id
        text url
        text raw_text
        string content_hash
        datetime posted_at
    }

    LEAD {
        uuid id PK
        uuid post_id FK
        string company_name
        string company_key
        string lead_type
        string_array skills
        string status
        float score
        float scam_risk
        uuid duplicate_of_lead_id FK
    }

    AGENT_IDENTITY {
        uuid id PK
        string name
        string role
        string api_key_hash
        string_array scopes
        boolean is_active
    }

    AGENT_RUN {
        uuid id PK
        uuid lead_id FK
        uuid agent_identity_id FK
        string status
        int steps_used
        int tokens_in
        int tokens_out
        decimal cost_usd
    }

    AGENT_STEP {
        uuid id PK
        uuid agent_run_id FK
        int step_no
        string tool_name
        jsonb tool_input
        jsonb tool_output
        int latency_ms
    }

    APPROVAL {
        uuid id PK
        uuid requested_by FK
        string action
        jsonb payload
        string status
        string decided_by
    }

    AUDIT_EVENT {
        uuid id PK
        string actor_type
        string actor_id
        string action
        string target_type
        string target_id
        string outcome
        text reason
    }

    LLM_CALL_LOG {
        uuid id PK
        string model
        string purpose
        int tokens_in
        int tokens_out
        int latency_ms
        decimal cost_usd_estimate
        boolean cached
    }
```

> [!NOTE]
> `audit_event` is strictly append-only. A PostgreSQL trigger function (`trg_audit_event_append_only`) raises an exception on any `UPDATE` or `DELETE` attempt.
