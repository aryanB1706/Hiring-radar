"""initial schema

Revision ID: 0f70f8d0a9ee
Revises:
Create Date: 2026-10-29 17:00:02.912441
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0f70f8d0a9ee"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# audit_event is append-only: any UPDATE, DELETE or TRUNCATE raises.
AUDIT_FUNCTION = """
CREATE FUNCTION audit_event_reject_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_event is append-only (% not allowed)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql
"""
AUDIT_ROW_TRIGGER = """
CREATE TRIGGER audit_event_no_update_delete
BEFORE UPDATE OR DELETE ON audit_event
FOR EACH ROW EXECUTE FUNCTION audit_event_reject_change()
"""
AUDIT_TRUNCATE_TRIGGER = """
CREATE TRIGGER audit_event_no_truncate
BEFORE TRUNCATE ON audit_event
FOR EACH STATEMENT EXECUTE FUNCTION audit_event_reject_change()
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "agent_identity",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "analyst",
                "outreach",
                "admin",
                name="role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("api_key_hash", sa.Text(), nullable=False),
        sa.Column(
            "scopes", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_identity")),
        sa.UniqueConstraint("api_key_hash", name=op.f("uq_agent_identity_api_key_hash")),
        sa.UniqueConstraint("name", name=op.f("uq_agent_identity_name")),
    )
    op.create_table(
        "audit_event",
        sa.Column(
            "actor_type",
            sa.Enum(
                "human",
                "agent",
                "system",
                name="actor_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column(
            "inputs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_event")),
    )
    op.create_index("ix_audit_event_created_at", "audit_event", ["created_at"], unique=False)
    op.create_index(
        "ix_audit_event_target", "audit_event", ["target_type", "target_id"], unique=False
    )
    op.create_table(
        "llm_call_log",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "cost_usd_estimate",
            sa.Numeric(precision=12, scale=6),
            server_default="0",
            nullable=False,
        ),
        sa.Column("cached", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_call_log")),
    )
    op.create_index("ix_llm_call_log_created_at", "llm_call_log", ["created_at"], unique=False)
    op.create_table(
        "party",
        sa.Column(
            "kind",
            sa.Enum(
                "person", "organization", name="kind", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column(
            "handles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_party")),
    )
    op.create_index("ix_party_normalized_name", "party", ["normalized_name"], unique=False)
    op.create_table(
        "source",
        sa.Column(
            "kind",
            sa.Enum(
                "hn",
                "reddit",
                "rss",
                "github",
                "search",
                "manual_paste",
                "csv_import",
                "linkedin_user_capture",
                name="kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source")),
        sa.UniqueConstraint("kind", "name", name="uq_source_kind_name"),
    )
    op.create_table(
        "approval",
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)",
            name=op.f("ck_approval_decided_iff_not_pending"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["agent_identity.id"],
            name=op.f("fk_approval_requested_by_agent_identity"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval")),
    )
    op.create_index("ix_approval_requested_by", "approval", ["requested_by"], unique=False)
    op.create_index("ix_approval_status", "approval", ["status"], unique=False)
    op.create_table(
        "post",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("author_handle", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["source.id"], name=op.f("fk_post_source_id_source"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_post")),
        sa.UniqueConstraint("source_id", "external_id", name="uq_post_source_id_external_id"),
    )
    op.create_index("ix_post_content_hash", "post", ["content_hash"], unique=False)
    op.create_index("ix_post_posted_at", "post", ["posted_at"], unique=False)
    op.create_table(
        "lead",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("party_id", sa.Uuid(), nullable=True),
        sa.Column("is_hiring", sa.Boolean(), nullable=True),
        sa.Column(
            "lead_type",
            sa.Enum(
                "hiring",
                "freelance_gig",
                "internship",
                "not_a_lead",
                name="lead_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("role_title", sa.Text(), nullable=True),
        sa.Column(
            "skills", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("seniority", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("is_remote", sa.Boolean(), nullable=True),
        sa.Column("budget_text", sa.Text(), nullable=True),
        sa.Column("budget_min", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("budget_max", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("urgency", sa.Text(), nullable=True),
        sa.Column("contact_method", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "new",
                "qualifying",
                "qualified",
                "needs_human",
                "rejected",
                "contacted",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="new",
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("scam_risk", sa.Float(), nullable=True),
        sa.Column("duplicate_of_lead_id", sa.Uuid(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
        sa.Column(
            "classified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("budget_min <= budget_max", name=op.f("ck_lead_budget_order")),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name=op.f("ck_lead_confidence_range")),
        sa.CheckConstraint("duplicate_of_lead_id <> id", name=op.f("ck_lead_not_own_duplicate")),
        sa.CheckConstraint("scam_risk BETWEEN 0 AND 1", name=op.f("ck_lead_scam_risk_range")),
        sa.ForeignKeyConstraint(
            ["duplicate_of_lead_id"],
            ["lead.id"],
            name=op.f("fk_lead_duplicate_of_lead_id_lead"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["party_id"], ["party.id"], name=op.f("fk_lead_party_id_party"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["post_id"], ["post.id"], name=op.f("fk_lead_post_id_post"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead")),
        sa.UniqueConstraint("post_id", name=op.f("uq_lead_post_id")),
    )
    op.create_index("ix_lead_duplicate_of_lead_id", "lead", ["duplicate_of_lead_id"], unique=False)
    op.create_index("ix_lead_lead_type", "lead", ["lead_type"], unique=False)
    op.create_index("ix_lead_party_id", "lead", ["party_id"], unique=False)
    op.create_index(
        "ix_lead_status_score",
        "lead",
        ["status", sa.literal_column("score DESC NULLS LAST")],
        unique=False,
    )
    op.create_table(
        "agent_run",
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("agent_identity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "succeeded",
                "failed",
                "needs_human",
                "budget_exceeded",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="running",
            nullable=False,
        ),
        sa.Column("steps_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_identity_id"],
            ["agent_identity.id"],
            name=op.f("fk_agent_run_agent_identity_id_agent_identity"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["lead.id"], name=op.f("fk_agent_run_lead_id_lead"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_run")),
    )
    op.create_index(
        "ix_agent_run_agent_identity_id", "agent_run", ["agent_identity_id"], unique=False
    )
    op.create_index("ix_agent_run_lead_id", "agent_run", ["lead_id"], unique=False)
    op.create_table(
        "enrichment",
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["lead.id"], name=op.f("fk_enrichment_lead_id_lead"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_enrichment")),
    )
    op.create_index("ix_enrichment_lead_id", "enrichment", ["lead_id"], unique=False)
    op.create_table(
        "feedback",
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_label",
            sa.Enum("good", "bad", name="user_label", native_enum=False, create_constraint=True),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["lead.id"], name=op.f("fk_feedback_lead_id_lead"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
    )
    op.create_index("ix_feedback_lead_id", "feedback", ["lead_id"], unique=False)
    op.create_table(
        "agent_step",
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("tool_input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tool_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_run.id"],
            name=op.f("fk_agent_step_agent_run_id_agent_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_step")),
        sa.UniqueConstraint("agent_run_id", "step_no", name="uq_agent_step_agent_run_id_step_no"),
    )
    op.execute(AUDIT_FUNCTION)
    op.execute(AUDIT_ROW_TRIGGER)
    op.execute(AUDIT_TRUNCATE_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_event_no_truncate ON audit_event")
    op.execute("DROP TRIGGER IF EXISTS audit_event_no_update_delete ON audit_event")
    op.execute("DROP FUNCTION IF EXISTS audit_event_reject_change()")
    op.drop_table("agent_step")
    op.drop_index("ix_feedback_lead_id", table_name="feedback")
    op.drop_table("feedback")
    op.drop_index("ix_enrichment_lead_id", table_name="enrichment")
    op.drop_table("enrichment")
    op.drop_index("ix_agent_run_lead_id", table_name="agent_run")
    op.drop_index("ix_agent_run_agent_identity_id", table_name="agent_run")
    op.drop_table("agent_run")
    op.drop_index("ix_lead_status_score", table_name="lead")
    op.drop_index("ix_lead_party_id", table_name="lead")
    op.drop_index("ix_lead_lead_type", table_name="lead")
    op.drop_index("ix_lead_duplicate_of_lead_id", table_name="lead")
    op.drop_table("lead")
    op.drop_index("ix_post_posted_at", table_name="post")
    op.drop_index("ix_post_content_hash", table_name="post")
    op.drop_table("post")
    op.drop_index("ix_approval_status", table_name="approval")
    op.drop_index("ix_approval_requested_by", table_name="approval")
    op.drop_table("approval")
    op.drop_table("source")
    op.drop_index("ix_party_normalized_name", table_name="party")
    op.drop_table("party")
    op.drop_index("ix_llm_call_log_created_at", table_name="llm_call_log")
    op.drop_table("llm_call_log")
    op.drop_index("ix_audit_event_target", table_name="audit_event")
    op.drop_index("ix_audit_event_created_at", table_name="audit_event")
    op.drop_table("audit_event")
    op.drop_table("agent_identity")
    op.execute("DROP EXTENSION IF EXISTS vector")
