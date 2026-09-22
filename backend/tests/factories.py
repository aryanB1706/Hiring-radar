"""Tiny helpers that insert valid rows so each test only spells out what it cares about."""

import datetime as dt
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import content_hash
from app.db.enums import AgentRole, LeadType, PartyKind, SourceKind
from app.db.models import AgentIdentity, Lead, Party, Post, Source


async def make_source(s: AsyncSession, name: str | None = None) -> Source:
    source = Source(kind=SourceKind.HN, name=name or f"hn-{uuid.uuid4().hex[:8]}")
    s.add(source)
    await s.flush()
    return source


async def make_post(
    s: AsyncSession,
    source: Source,
    external_id: str | None = None,
    *,
    text: str = "We are hiring a Python developer",
    posted_at: dt.datetime | None = None,
) -> Post:
    post = Post(
        source_id=source.id,
        external_id=external_id or uuid.uuid4().hex,
        url="https://example.com/post",
        raw_text=text,
        content_hash=content_hash(text),
        posted_at=posted_at,
    )
    s.add(post)
    await s.flush()
    return post


async def make_lead(s: AsyncSession, post: Post, **overrides: object) -> Lead:
    fields: dict[str, object] = {
        "post_id": post.id,
        "lead_type": LeadType.HIRING,
        "confidence": 0.9,
    }
    lead = Lead(**(fields | overrides))
    s.add(lead)
    await s.flush()
    return lead


async def make_party(s: AsyncSession, name: str = "Acme") -> Party:
    party = Party(kind=PartyKind.ORGANIZATION, display_name=name, normalized_name=name.lower())
    s.add(party)
    await s.flush()
    return party


async def make_agent(s: AsyncSession, name: str | None = None) -> AgentIdentity:
    agent = AgentIdentity(
        name=name or f"agent-{uuid.uuid4().hex[:8]}",
        role=AgentRole.ANALYST,
        api_key_hash=uuid.uuid4().hex,
    )
    s.add(agent)
    await s.flush()
    return agent
