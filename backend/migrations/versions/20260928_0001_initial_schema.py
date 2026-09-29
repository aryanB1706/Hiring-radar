"""Initial relational schema with append-only audit trigger.

Revision ID: 20260928_0001
Revises:
Create Date: 2026-09-28 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260928_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create Enums
    source_kind = postgresql.ENUM(
        "hn",
        "reddit",
        "manual_paste",
        "csv_import",
        "user_capture",
        name="source_kind",
        create_type=False,
    )
    source_kind.create(op.get_bind(), checkfirst=True)

    lead_type = postgresql.ENUM(
        "hiring",
        "freelance_gig",
        "internship",
        "not_a_lead",
        name="lead_type",
        create_type=False,
    )
    lead_type.create(op.get_bind(), checkfirst=True)

    lead_status = postgresql.ENUM(
        "new",
        "qualifying",
        "qualified",
        "needs_human",
        "rejected",
        "contacted",
        name="lead_status",
        create_type=False,
    )
    lead_status.create(op.get_bind(), checkfirst=True)

    agent_role = postgresql.ENUM("analyst", "outreach", name="agent_role", create_type=False)
    agent_role.create(op.get_bind(), checkfirst=True)

    approval_status = postgresql.ENUM(
        "pending",
        "approved",
        "rejected",
        "executed",
        name="approval_status",
        create_type=False,
    )
    approval_status.create(op.get_bind(), checkfirst=True)

    actor_type = postgresql.ENUM("human", "agent", "system", name="actor_type", create_type=False)
    actor_type.create(op.get_bind(), checkfirst=True)

    audit_outcome = postgresql.ENUM(
        "allowed",
        "denied",
        "pending",
        "executed",
        "error",
        name="audit_outcome",
        create_type=False,
    )
    audit_outcome.create(op.get_bind(), checkfirst=True)

    # 2. Table: source
    op.create_table(
        "source",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", source_kind, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # 3. Table: post
    op.create_table(
        "post",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("author_handle", sa.String(255), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("source_id", "external_id", name="uq_post_source_external_id"),
    )
    op.create_index("ix_post_content_hash", "post", ["content_hash"])
    op.create_index("ix_post_posted_at", "post", ["posted_at"])

    # 4. Table: lead
    op.create_table(
        "lead",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("post.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("company_key", sa.String(255), nullable=True),
        sa.Column("is_hiring", sa.Boolean(), nullable=True),
        sa.Column("lead_type", lead_type, nullable=False),
        sa.Column("role_title", sa.String(255), nullable=True),
        sa.Column(
            "skills",
            sa.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("seniority", sa.String(50), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("is_remote", sa.Boolean(), nullable=True),
        sa.Column("budget_text", sa.String(255), nullable=True),
        sa.Column("budget_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("budget_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("urgency", sa.String(50), nullable=True),
        sa.Column("contact_method", sa.String(255), nullable=True),
        sa.Column("confidence", sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=True),
        sa.Column(
            "evidence_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("status", lead_status, server_default=sa.text("'new'"), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("scam_risk", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "duplicate_of_lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lead.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_lead_status_score", "lead", ["status", "score"])
    op.create_index("ix_lead_lead_type", "lead", ["lead_type"])
    op.create_index("ix_lead_company_key", "lead", ["company_key"])

    # 5. Table: agent_identity
    op.create_table(
        "agent_identity",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("role", agent_role, nullable=False),
        sa.Column("api_key_hash", sa.String(255), nullable=False),
        sa.Column(
            "scopes",
            sa.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # 6. Table: agent_run
    op.create_table(
        "agent_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lead.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_identity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_identity.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(50), server_default=sa.text("'running'"), nullable=False),
        sa.Column("steps_used", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), server_default=sa.text("0.0"), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # 7. Table: agent_step
    op.create_table(
        "agent_step",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column(
            "tool_input",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("tool_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # 8. Table: approval
    op.create_table(
        "approval",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "requested_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_identity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", approval_status, server_default=sa.text("'pending'"), nullable=False),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # 9. Table: audit_event
    op.create_table(
        "audit_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_type", actor_type, nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=False),
        sa.Column(
            "inputs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("outcome", audit_outcome, nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # 10. Table: llm_call_log
    op.create_table(
        "llm_call_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cost_usd_estimate", sa.Numeric(10, 6), server_default=sa.text("0.0"), nullable=False
        ),
        sa.Column("cached", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # 11. Trigger: Enforce Append-Only for audit_event
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_audit_event_append_only()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_event table is append-only. Updates and deletes are not allowed.';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_event_append_only
        BEFORE UPDATE OR DELETE ON audit_event
        FOR EACH ROW
        EXECUTE FUNCTION enforce_audit_event_append_only();
        """
    )


def downgrade() -> None:
    # 1. Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS trg_audit_event_append_only ON audit_event;")
    op.execute("DROP FUNCTION IF EXISTS enforce_audit_event_append_only();")

    # 2. Drop tables in reverse order
    op.drop_table("llm_call_log")
    op.drop_table("audit_event")
    op.drop_table("approval")
    op.drop_table("agent_step")
    op.drop_table("agent_run")
    op.drop_table("agent_identity")
    op.drop_index("ix_lead_company_key", table_name="lead")
    op.drop_index("ix_lead_lead_type", table_name="lead")
    op.drop_index("ix_lead_status_score", table_name="lead")
    op.drop_table("lead")
    op.drop_index("ix_post_posted_at", table_name="post")
    op.drop_index("ix_post_content_hash", table_name="post")
    op.drop_table("post")
    op.drop_table("source")

    # 3. Drop Enums
    op.execute("DROP TYPE IF EXISTS audit_outcome;")
    op.execute("DROP TYPE IF EXISTS actor_type;")
    op.execute("DROP TYPE IF EXISTS approval_status;")
    op.execute("DROP TYPE IF EXISTS agent_role;")
    op.execute("DROP TYPE IF EXISTS lead_status;")
    op.execute("DROP TYPE IF EXISTS lead_type;")
    op.execute("DROP TYPE IF EXISTS source_kind;")
