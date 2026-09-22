import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import PartyKind
from app.db.models import Party

_LEGAL_SUFFIXES = {
    "inc", "llc", "ltd", "limited", "pvt", "private", "corp", "corporation", "gmbh", "co",
}  # fmt: skip


def normalize_company(name: str) -> str:
    """'Acme Pvt. Ltd.' and 'ACME' share one normalized name."""
    tokens = re.sub(r"[^a-z0-9]+", " ", name.casefold()).split()
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


async def get_or_create_organization(session: AsyncSession, display_name: str) -> Party:
    normalized = normalize_company(display_name)
    existing = (
        await session.execute(
            select(Party)
            .where(Party.kind == PartyKind.ORGANIZATION, Party.normalized_name == normalized)
            .order_by(Party.created_at, Party.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    party = Party(
        kind=PartyKind.ORGANIZATION, display_name=display_name, normalized_name=normalized
    )
    session.add(party)
    await session.flush()
    return party
