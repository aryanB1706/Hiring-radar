import datetime as dt
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.classifier.service import FLAGS_KIND
from app.db.enums import LeadStatus, LeadType
from app.db.models import Enrichment
from tests.factories import make_lead, make_party, make_post, make_source

T0 = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)


@pytest.fixture
async def leads(session: AsyncSession) -> dict[str, uuid.UUID]:
    """a: remote python hiring (scored); b: on-site django gig; c: duplicate of a; d: noise."""
    source = await make_source(session)
    acme = await make_party(session, "Acme")

    async def lead(name: str, minutes: int, **fields: object):  # type: ignore[no-untyped-def]
        post = await make_post(session, source, text=f"post {name}", posted_at=T0)
        base = {"classified_at": T0 + dt.timedelta(minutes=minutes)}
        return await make_lead(session, post, **(base | fields))

    a = await lead(
        "a", 1, skills=["python", "fastapi"], is_remote=True, confidence=0.9, score=80.0,
        party_id=acme.id, role_title="Python Developer", evidence_quote="hiring",
    )  # fmt: skip
    b = await lead(
        "b", 2, lead_type=LeadType.FREELANCE_GIG, skills=["django"], is_remote=False, confidence=0.5
    )
    c = await lead("c", 3, skills=["python"], is_remote=True, duplicate_of_lead_id=a.id)
    d = await lead(
        "d", 4, lead_type=LeadType.NOT_A_LEAD, status=LeadStatus.REJECTED, confidence=0.95
    )
    return {"a": a.id, "b": b.id, "c": c.id, "d": d.id}


def ids(page: dict) -> list[str]:
    return [item["id"] for item in page["items"]]


async def test_duplicates_are_hidden_unless_asked_for(
    client: AsyncClient, leads: dict[str, uuid.UUID]
) -> None:
    default = (await client.get("/api/leads")).json()
    assert default["total"] == 3
    assert str(leads["c"]) not in ids(default)

    everything = (await client.get("/api/leads", params={"include_duplicates": True})).json()
    assert everything["total"] == 4


async def test_ranked_by_score_then_newest(
    client: AsyncClient, leads: dict[str, uuid.UUID]
) -> None:
    page = (await client.get("/api/leads")).json()
    assert ids(page) == [
        str(leads["a"]),
        str(leads["d"]),
        str(leads["b"]),
    ]  # scored first, then newest


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"lead_type": "freelance_gig"}, ["b"]),
        ({"status": "rejected"}, ["d"]),
        ({"is_remote": "true"}, ["a"]),
        ({"is_remote": "false"}, ["b"]),
        ({"skill": "Python"}, ["a"]),  # case-insensitive; the duplicate c is hidden
        ({"skill": "django"}, ["b"]),
        ({"min_confidence": 0.8}, ["a", "d"]),
        ({"lead_type": "hiring", "min_confidence": 0.8}, ["a"]),
        ({"skill": "rust"}, []),
    ],
)
async def test_filters(
    client: AsyncClient, leads: dict[str, uuid.UUID], params: dict, expected: list[str]
) -> None:
    page = (await client.get("/api/leads", params=params)).json()
    assert sorted(ids(page)) == sorted(str(leads[k]) for k in expected)
    assert page["total"] == len(expected)


async def test_pagination(client: AsyncClient, leads: dict[str, uuid.UUID]) -> None:
    first = (await client.get("/api/leads", params={"limit": 2, "offset": 0})).json()
    second = (await client.get("/api/leads", params={"limit": 2, "offset": 2})).json()
    assert (first["total"], len(first["items"]), len(second["items"])) == (3, 2, 1)
    assert not set(ids(first)) & set(ids(second))


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"min_confidence": 2}, {"lead_type": "bogus"}],
)
async def test_bad_query_parameters_are_rejected(client: AsyncClient, params: dict) -> None:
    assert (await client.get("/api/leads", params=params)).status_code == 422


async def test_lead_detail_has_company_post_text_and_flags(
    client: AsyncClient, session: AsyncSession, leads: dict[str, uuid.UUID]
) -> None:
    session.add(
        Enrichment(
            lead_id=leads["a"], kind=FLAGS_KIND, data={"flags": ["evidence_quote_not_in_post"]}
        )
    )
    await session.flush()

    body = (await client.get(f"/api/leads/{leads['a']}")).json()

    assert body["company_name"] == "Acme"
    assert (body["role_title"], body["skills"], body["score"]) == (
        "Python Developer",
        ["python", "fastapi"],
        80.0,
    )
    assert body["raw_text"] == "post a"
    assert body["flags"] == ["evidence_quote_not_in_post"]
    assert body["post"]["url"] == "https://example.com/post"
    assert body["post"]["source_kind"] == "hn"


async def test_unknown_lead_is_404_and_bad_id_is_422(client: AsyncClient) -> None:
    assert (await client.get(f"/api/leads/{uuid.uuid4()}")).status_code == 404
    assert (await client.get("/api/leads/not-a-uuid")).status_code == 422
