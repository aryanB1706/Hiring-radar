"""Database schema and constraint validation tests."""

import uuid

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.enums import (
    ActorType,
    AuditOutcome,
    LeadStatus,
    LeadType,
    SourceKind,
)
from app.db.models import AuditEvent, Lead, Post, Source


def test_post_source_external_id_unique_constraint(db_session) -> None:
    """Verifies that duplicate (source_id, external_id) inserts are blocked."""
    source = Source(
        id=uuid.uuid4(),
        kind=SourceKind.HN,
        name="Hacker News Who is Hiring",
        enabled=True,
        config={},
    )
    db_session.add(source)
    db_session.flush()

    post1 = Post(
        id=uuid.uuid4(),
        source_id=source.id,
        external_id="hn_item_12345",
        url="https://news.ycombinator.com/item?id=12345",
        raw_text="Acme Corp is hiring a Senior Python Engineer.",
        content_hash="abc123hash",
    )
    db_session.add(post1)
    db_session.flush()

    post2 = Post(
        id=uuid.uuid4(),
        source_id=source.id,
        external_id="hn_item_12345",  # Duplicate external_id for same source
        url="https://news.ycombinator.com/item?id=12345",
        raw_text="Another text with identical external id",
        content_hash="def456hash",
    )
    db_session.add(post2)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_audit_event_append_only_blocks_update(db_session) -> None:
    """Verifies that the PostgreSQL trigger prevents UPDATE on audit_event."""
    event = AuditEvent(
        id=uuid.uuid4(),
        actor_type=ActorType.AGENT,
        actor_id="agent_analyst_01",
        action="qualify_lead",
        target_type="lead",
        target_id="lead_987",
        inputs={"tool": "search_company"},
        outcome=AuditOutcome.ALLOWED,
        reason="Initial qualification pass",
    )
    db_session.add(event)
    db_session.flush()

    # Attempt to modify the audit record
    event.reason = "Tampered reason string"
    with pytest.raises(DBAPIError) as exc_info:
        db_session.flush()

    assert "audit_event table is append-only" in str(exc_info.value)


def test_audit_event_append_only_blocks_delete(db_session) -> None:
    """Verifies that the PostgreSQL trigger prevents DELETE on audit_event."""
    event = AuditEvent(
        id=uuid.uuid4(),
        actor_type=ActorType.HUMAN,
        actor_id="recruiter_admin",
        action="manual_lead_approval",
        target_type="approval",
        target_id="appr_001",
        inputs={},
        outcome=AuditOutcome.EXECUTED,
        reason="Approved by human reviewer",
    )
    db_session.add(event)
    db_session.flush()

    # Attempt to delete the audit record
    db_session.delete(event)
    with pytest.raises(DBAPIError) as exc_info:
        db_session.flush()

    assert "audit_event table is append-only" in str(exc_info.value)


def test_foreign_key_cascade_deletion(db_session) -> None:
    """Verifies cascading deletion from source down to post and lead."""
    source = Source(
        id=uuid.uuid4(),
        kind=SourceKind.REDDIT,
        name="r/forhire",
        enabled=True,
        config={},
    )
    db_session.add(source)
    db_session.flush()

    post = Post(
        id=uuid.uuid4(),
        source_id=source.id,
        external_id="reddit_post_999",
        url="https://reddit.com/r/forhire/comments/999",
        raw_text="[Hiring] Backend Developer needed",
        content_hash="hash999",
    )
    db_session.add(post)
    db_session.flush()

    lead = Lead(
        id=uuid.uuid4(),
        post_id=post.id,
        lead_type=LeadType.HIRING,
        role_title="Backend Developer",
        skills=["Python", "FastAPI"],
        confidence=0.95,
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.flush()

    post_id = post.id
    lead_id = lead.id

    # Deleting source should cascade-delete post and lead
    db_session.delete(source)
    db_session.flush()

    assert db_session.get(Post, post_id) is None
    assert db_session.get(Lead, lead_id) is None


def test_lead_duplicate_self_reference(db_session) -> None:
    """Verifies that duplicate_of_lead_id correctly models duplicate lead relationships."""
    source = Source(
        id=uuid.uuid4(),
        kind=SourceKind.MANUAL_PASTE,
        name="User Manual Paste",
        enabled=True,
        config={},
    )
    db_session.add(source)
    db_session.flush()

    post1 = Post(
        id=uuid.uuid4(),
        source_id=source.id,
        external_id="paste_1",
        url="https://example.com/1",
        raw_text="Post 1",
        content_hash="hash1",
    )
    post2 = Post(
        id=uuid.uuid4(),
        source_id=source.id,
        external_id="paste_2",
        url="https://example.com/2",
        raw_text="Post 2",
        content_hash="hash2",
    )
    db_session.add_all([post1, post2])
    db_session.flush()

    canonical_lead = Lead(
        id=uuid.uuid4(),
        post_id=post1.id,
        lead_type=LeadType.HIRING,
        role_title="Python Engineer",
        skills=["Python"],
        status=LeadStatus.QUALIFIED,
    )
    db_session.add(canonical_lead)
    db_session.flush()

    duplicate_lead = Lead(
        id=uuid.uuid4(),
        post_id=post2.id,
        lead_type=LeadType.HIRING,
        role_title="Python Engineer",
        skills=["Python"],
        status=LeadStatus.REJECTED,
        duplicate_of_lead_id=canonical_lead.id,
    )
    db_session.add(duplicate_lead)
    db_session.flush()

    loaded_duplicate = db_session.get(Lead, duplicate_lead.id)
    assert loaded_duplicate is not None
    assert loaded_duplicate.duplicate_of_lead_id == canonical_lead.id
