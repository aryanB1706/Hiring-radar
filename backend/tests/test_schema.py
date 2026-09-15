import uuid

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ActorType, AgentRunStatus, ApprovalStatus
from app.db.models import (
    AgentIdentity,
    AgentRun,
    Approval,
    AuditEvent,
    Enrichment,
    Feedback,
    Lead,
    Party,
    Post,
    Source,
)
from tests.factories import make_agent, make_lead, make_party, make_post, make_source


async def test_post_unique_per_source_and_external_id(session: AsyncSession) -> None:
    source = await make_source(session)
    await make_post(session, source, external_id="42")

    with pytest.raises(IntegrityError, match="uq_post_source_id_external_id"):
        async with session.begin_nested():
            await make_post(session, source, external_id="42")

    # The same external id under another source is fine.
    other = await make_source(session)
    await make_post(session, other, external_id="42")


async def test_one_lead_per_post(session: AsyncSession) -> None:
    post = await make_post(session, await make_source(session))
    await make_lead(session, post)
    with pytest.raises(IntegrityError, match="uq_lead_post_id"):
        async with session.begin_nested():
            await make_lead(session, post)


async def test_database_rejects_invalid_enum_and_ranges(session: AsyncSession) -> None:
    post = await make_post(session, await make_source(session))
    with pytest.raises(IntegrityError, match="ck_lead_lead_type"):
        async with session.begin_nested():
            await session.execute(
                text("INSERT INTO lead (post_id, lead_type, confidence) VALUES (:p, 'spam', 0.5)"),
                {"p": post.id},
            )
    with pytest.raises(IntegrityError, match="ck_lead_confidence_range"):
        async with session.begin_nested():
            await make_lead(session, post, confidence=1.5)


# --- audit_event is append-only -------------------------------------------------------------


async def _audit_event(session: AsyncSession) -> AuditEvent:
    event = AuditEvent(
        actor_type=ActorType.SYSTEM,
        actor_id="test",
        action="lead.create",
        target_type="lead",
        target_id="1",
        outcome="ok",
    )
    session.add(event)
    await session.flush()
    return event


async def test_audit_event_insert_is_allowed(session: AsyncSession) -> None:
    event = await _audit_event(session)
    assert event.id is not None


async def test_audit_event_update_is_blocked(session: AsyncSession) -> None:
    event = await _audit_event(session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin_nested():
            await session.execute(
                update(AuditEvent).where(AuditEvent.id == event.id).values(outcome="tampered")
            )


async def test_audit_event_delete_is_blocked(session: AsyncSession) -> None:
    event = await _audit_event(session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin_nested():
            await session.execute(delete(AuditEvent).where(AuditEvent.id == event.id))


async def test_audit_event_truncate_is_blocked(session: AsyncSession) -> None:
    await _audit_event(session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin_nested():
            await session.execute(text("TRUNCATE audit_event"))


# --- foreign key behaviour ------------------------------------------------------------------


async def test_lead_requires_existing_post(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="fk_lead_post_id_post"):
        async with session.begin_nested():
            session.add(
                Lead(post_id=uuid.uuid4(), lead_type="hiring", confidence=0.5)  # type: ignore[arg-type]
            )
            await session.flush()


async def test_cannot_delete_source_that_has_posts(session: AsyncSession) -> None:
    source = await make_source(session)
    await make_post(session, source)
    with pytest.raises(IntegrityError, match="fk_post_source_id_source"):
        async with session.begin_nested():
            await session.execute(delete(Source).where(Source.id == source.id))


async def test_deleting_post_cascades_to_lead_and_children(session: AsyncSession) -> None:
    post = await make_post(session, await make_source(session))
    lead = await make_lead(session, post)
    session.add_all(
        [
            Enrichment(lead_id=lead.id, kind="company", data={"name": "Acme"}),
            Feedback(lead_id=lead.id, user_label="good"),  # type: ignore[arg-type]
        ]
    )
    await session.flush()

    await session.execute(delete(Post).where(Post.id == post.id))

    for model in (Lead, Enrichment, Feedback):
        assert (await session.execute(select(model))).first() is None


async def test_deleting_party_or_original_lead_sets_null(session: AsyncSession) -> None:
    source = await make_source(session)
    party = await make_party(session)
    original = await make_lead(session, await make_post(session, source))
    dup = await make_lead(
        session,
        await make_post(session, source),
        party_id=party.id,
        duplicate_of_lead_id=original.id,
    )

    await session.execute(delete(Party).where(Party.id == party.id))
    await session.execute(delete(Lead).where(Lead.id == original.id))
    await session.refresh(dup)

    assert dup.party_id is None
    assert dup.duplicate_of_lead_id is None


async def test_cannot_delete_agent_that_has_runs_or_approvals(session: AsyncSession) -> None:
    agent = await make_agent(session)
    lead = await make_lead(session, await make_post(session, await make_source(session)))
    run = AgentRun(lead_id=lead.id, agent_identity_id=agent.id)
    session.add(run)
    await session.flush()
    await session.refresh(run)
    assert run.status == AgentRunStatus.RUNNING  # server default

    with pytest.raises(IntegrityError, match="fk_agent_run_agent_identity_id_agent_identity"):
        async with session.begin_nested():
            await session.execute(delete(AgentIdentity).where(AgentIdentity.id == agent.id))


async def test_approval_decision_fields_must_match_status(session: AsyncSession) -> None:
    agent = await make_agent(session)
    session.add(Approval(requested_by=agent.id, action="send", payload={}))
    await session.flush()  # pending without decided_at is valid

    with pytest.raises(IntegrityError, match="ck_approval_decided_iff_not_pending"):
        async with session.begin_nested():
            session.add(
                Approval(
                    requested_by=agent.id,
                    action="send",
                    payload={},
                    status=ApprovalStatus.APPROVED,  # approved but no decided_at
                )
            )
            await session.flush()


# --- pgvector -------------------------------------------------------------------------------


def _unit_vector(index: int, dim: int = 384) -> list[float]:
    return [1.0 if i == index else 0.0 for i in range(dim)]


async def test_pgvector_nearest_neighbour(session: AsyncSession) -> None:
    for i, name in enumerate(["near-0", "near-1", "near-2"]):
        party = await make_party(session, name)
        party.embedding = _unit_vector(i)
    await session.flush()

    query = _unit_vector(1)
    result = await session.execute(
        select(Party.display_name).order_by(Party.embedding.cosine_distance(query)).limit(1)
    )
    assert result.scalar_one() == "near-1"
