import datetime as dt
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.classifier.batch import MAX_ATTEMPTS, classify_pending, pending_posts
from app.classifier.service import ClassifierService
from app.db.enums import ActorType
from app.db.models import AuditEvent, Lead
from app.embeddings import FakeEmbedder
from app.llm import FakeLLMClient
from tests.factories import make_lead, make_post, make_source

T0 = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)


def good(role: str) -> str:
    return json.dumps(
        {
            "lead_type": "hiring",
            "confidence": 0.9,
            "evidence_quote": "hiring",
            "role_title": role,
            "skills": [role.lower()],
        }
    )


def service_for(session: AsyncSession, llm: FakeLLMClient) -> ClassifierService:
    return ClassifierService(session, llm, FakeEmbedder(), dedupe_threshold=0.08)


async def post_at(session: AsyncSession, n: int, text: str | None = None):  # type: ignore[no-untyped-def]
    return await make_post(
        session,
        await make_source(session),
        text=text or f"We are hiring a person for role number {n}",
        posted_at=T0 + dt.timedelta(days=n),
    )


async def test_a_bad_llm_reply_does_not_stop_the_batch(session: AsyncSession) -> None:
    first, broken, last = [await post_at(session, n) for n in (1, 2, 3)]
    # Oldest first: post 1 ok, post 2 gets garbage on every attempt, post 3 ok.
    llm = FakeLLMClient([good("Alpha"), "garbage", "garbage", "garbage", good("Omega")])

    summary = await classify_pending(session, service_for(session, llm), batch_size=10)

    assert (summary.selected, summary.classified, summary.failed) == (3, 2, 1)
    leads = (await session.execute(select(Lead.post_id))).scalars().all()
    assert set(leads) == {first.id, last.id}
    [event] = (await session.execute(select(AuditEvent))).scalars().all()
    assert (event.actor_type, event.action, event.outcome) == (
        ActorType.SYSTEM,
        "classify_post",
        "error",
    )
    assert event.target_id == str(broken.id)
    assert "StructuredOutputError" in (event.reason or "")


async def test_a_post_that_keeps_failing_is_eventually_left_alone(session: AsyncSession) -> None:
    await post_at(session, 1)
    for attempt in range(MAX_ATTEMPTS):
        llm = FakeLLMClient(responder=lambda prompt: "garbage")
        summary = await classify_pending(session, service_for(session, llm), batch_size=10)
        assert (summary.selected, summary.failed) == (1, 1), f"attempt {attempt}"

    llm = FakeLLMClient(responder=lambda prompt: "garbage")
    summary = await classify_pending(session, service_for(session, llm), batch_size=10)

    assert summary.selected == 0 and llm.calls == []


async def test_only_posts_without_a_lead_are_picked_oldest_first(session: AsyncSession) -> None:
    done, newer, older = (
        await post_at(session, 5),
        await post_at(session, 9),
        await post_at(session, 2),
    )
    await make_lead(session, done)

    pending = await pending_posts(session, limit=10)

    assert [p.id for p in pending] == [older.id, newer.id]
    assert [p.id for p in await pending_posts(session, limit=1)] == [older.id]


async def test_prefiltered_posts_are_counted_and_cost_no_llm_calls(session: AsyncSession) -> None:
    await post_at(session, 1, text="lovely weather in the mountains this weekend")
    await post_at(session, 2, text="We are hiring a Python developer")
    llm = FakeLLMClient([good("Python")])

    summary = await classify_pending(session, service_for(session, llm), batch_size=10)

    assert (summary.classified, summary.prefiltered, summary.llm_calls) == (2, 1, 1)
    assert len(llm.calls) == 1


async def test_rerunning_a_finished_batch_does_nothing(session: AsyncSession) -> None:
    await post_at(session, 1)
    llm = FakeLLMClient([good("Python")])
    await classify_pending(session, service_for(session, llm), batch_size=10)

    again = await classify_pending(session, service_for(session, llm), batch_size=10)

    assert again.selected == 0
    assert (await session.execute(select(func.count()).select_from(Lead))).scalar_one() == 1
