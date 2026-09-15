import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey, enum_type
from app.db.enums import (
    ActorType,
    AgentRole,
    AgentRunStatus,
    ApprovalStatus,
    FeedbackLabel,
    LeadStatus,
    LeadType,
    PartyKind,
    SourceKind,
)

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


def _jsonb_default(literal: str) -> sa.TextClause:
    return text(f"'{literal}'::jsonb")


def _timestamptz(**kwargs: Any) -> Mapped[Any]:
    return mapped_column(sa.DateTime(timezone=True), **kwargs)


class Source(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "source"
    __table_args__ = (UniqueConstraint("kind", "name", name="uq_source_kind_name"),)

    kind: Mapped[SourceKind] = mapped_column(enum_type(SourceKind, "kind"))
    name: Mapped[str] = mapped_column(sa.Text)
    enabled: Mapped[bool] = mapped_column(server_default=sa.true())
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=_jsonb_default("{}"))


class Post(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "post"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_post_source_id_external_id"),
        Index("ix_post_content_hash", "content_hash"),
        Index("ix_post_posted_at", "posted_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id", ondelete="RESTRICT"))
    external_id: Mapped[str] = mapped_column(sa.Text)
    url: Mapped[str] = mapped_column(sa.Text)
    author_handle: Mapped[str | None] = mapped_column(sa.Text)
    raw_text: Mapped[str] = mapped_column(sa.Text)
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    posted_at: Mapped[dt.datetime | None] = _timestamptz()
    fetched_at: Mapped[dt.datetime] = _timestamptz(server_default=func.now())
    language: Mapped[str | None] = mapped_column(sa.String(16))


class Party(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "party"
    __table_args__ = (Index("ix_party_normalized_name", "normalized_name"),)

    kind: Mapped[PartyKind] = mapped_column(enum_type(PartyKind, "kind"))
    display_name: Mapped[str] = mapped_column(sa.Text)
    normalized_name: Mapped[str] = mapped_column(sa.Text)
    website: Mapped[str | None] = mapped_column(sa.Text)
    email: Mapped[str | None] = mapped_column(sa.Text)
    handles: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=_jsonb_default("{}"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class Lead(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "lead"
    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("scam_risk BETWEEN 0 AND 1", name="scam_risk_range"),
        CheckConstraint("budget_min <= budget_max", name="budget_order"),
        CheckConstraint("duplicate_of_lead_id <> id", name="not_own_duplicate"),
        Index("ix_lead_status_score", "status", text("score DESC NULLS LAST")),
        Index("ix_lead_lead_type", "lead_type"),
        Index("ix_lead_party_id", "party_id"),
        Index("ix_lead_duplicate_of_lead_id", "duplicate_of_lead_id"),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("post.id", ondelete="CASCADE"), unique=True
    )
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("party.id", ondelete="SET NULL"))
    is_hiring: Mapped[bool | None] = mapped_column()
    lead_type: Mapped[LeadType] = mapped_column(enum_type(LeadType, "lead_type"))
    role_title: Mapped[str | None] = mapped_column(sa.Text)
    skills: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), server_default=text("'{}'"))
    seniority: Mapped[str | None] = mapped_column(sa.Text)
    location: Mapped[str | None] = mapped_column(sa.Text)
    is_remote: Mapped[bool | None] = mapped_column()
    budget_text: Mapped[str | None] = mapped_column(sa.Text)
    budget_min: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2))
    budget_max: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(sa.String(8))
    urgency: Mapped[str | None] = mapped_column(sa.Text)
    contact_method: Mapped[str | None] = mapped_column(sa.Text)
    confidence: Mapped[float] = mapped_column(sa.Float)
    evidence_quote: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[LeadStatus] = mapped_column(
        enum_type(LeadStatus, "status"), server_default=LeadStatus.NEW.value
    )
    score: Mapped[float | None] = mapped_column(sa.Float)
    scam_risk: Mapped[float | None] = mapped_column(sa.Float)
    duplicate_of_lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lead.id", ondelete="SET NULL")
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    classified_at: Mapped[dt.datetime] = _timestamptz(server_default=func.now())


class Enrichment(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "enrichment"
    __table_args__ = (Index("ix_enrichment_lead_id", "lead_id"),)

    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(sa.Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_url: Mapped[str | None] = mapped_column(sa.Text)


class AgentIdentity(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "agent_identity"

    name: Mapped[str] = mapped_column(sa.Text, unique=True)
    role: Mapped[AgentRole] = mapped_column(enum_type(AgentRole, "role"))
    api_key_hash: Mapped[str] = mapped_column(sa.Text, unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), server_default=text("'{}'"))
    is_active: Mapped[bool] = mapped_column(server_default=sa.true())


class AgentRun(UUIDPrimaryKey, Base):
    __tablename__ = "agent_run"
    __table_args__ = (
        Index("ix_agent_run_lead_id", "lead_id"),
        Index("ix_agent_run_agent_identity_id", "agent_identity_id"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead.id", ondelete="CASCADE"))
    agent_identity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_identity.id", ondelete="RESTRICT")
    )
    status: Mapped[AgentRunStatus] = mapped_column(
        enum_type(AgentRunStatus, "status"), server_default=AgentRunStatus.RUNNING.value
    )
    steps_used: Mapped[int] = mapped_column(server_default="0")
    tokens_in: Mapped[int] = mapped_column(server_default="0")
    tokens_out: Mapped[int] = mapped_column(server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(sa.Numeric(12, 6), server_default="0")
    started_at: Mapped[dt.datetime] = _timestamptz(server_default=func.now())
    finished_at: Mapped[dt.datetime | None] = _timestamptz()
    error: Mapped[str | None] = mapped_column(sa.Text)


class AgentStep(UUIDPrimaryKey, Base):
    __tablename__ = "agent_step"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "step_no", name="uq_agent_step_agent_run_id_step_no"),
    )

    agent_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.id", ondelete="CASCADE"))
    step_no: Mapped[int] = mapped_column()
    tool_name: Mapped[str] = mapped_column(sa.Text)
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    tool_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(sa.Text)
    latency_ms: Mapped[int] = mapped_column()


class Approval(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "approval"
    __table_args__ = (
        CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)", name="decided_iff_not_pending"
        ),
        Index("ix_approval_status", "status"),
        Index("ix_approval_requested_by", "requested_by"),
    )

    requested_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_identity.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(sa.Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus, "status"), server_default=ApprovalStatus.PENDING.value
    )
    decided_by: Mapped[str | None] = mapped_column(sa.Text)
    decided_at: Mapped[dt.datetime | None] = _timestamptz()


class AuditEvent(UUIDPrimaryKey, CreatedAt, Base):
    """Append-only: a database trigger rejects UPDATE, DELETE and TRUNCATE."""

    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_event_target", "target_type", "target_id"),
        Index("ix_audit_event_created_at", "created_at"),
    )

    actor_type: Mapped[ActorType] = mapped_column(enum_type(ActorType, "actor_type"))
    actor_id: Mapped[str] = mapped_column(sa.Text)
    action: Mapped[str] = mapped_column(sa.Text)
    target_type: Mapped[str] = mapped_column(sa.Text)
    target_id: Mapped[str | None] = mapped_column(sa.Text)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=_jsonb_default("{}"))
    outcome: Mapped[str] = mapped_column(sa.Text)
    reason: Mapped[str | None] = mapped_column(sa.Text)


class Feedback(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "feedback"
    __table_args__ = (Index("ix_feedback_lead_id", "lead_id"),)

    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead.id", ondelete="CASCADE"))
    user_label: Mapped[FeedbackLabel] = mapped_column(enum_type(FeedbackLabel, "user_label"))
    note: Mapped[str | None] = mapped_column(sa.Text)


class LLMCallLog(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "llm_call_log"
    __table_args__ = (Index("ix_llm_call_log_created_at", "created_at"),)

    provider: Mapped[str] = mapped_column(sa.Text)
    model: Mapped[str] = mapped_column(sa.Text)
    purpose: Mapped[str] = mapped_column(sa.Text)
    tokens_in: Mapped[int] = mapped_column(server_default="0")
    tokens_out: Mapped[int] = mapped_column(server_default="0")
    latency_ms: Mapped[int] = mapped_column()
    cost_usd_estimate: Mapped[Decimal] = mapped_column(sa.Numeric(12, 6), server_default="0")
    cached: Mapped[bool] = mapped_column(server_default=sa.false())
