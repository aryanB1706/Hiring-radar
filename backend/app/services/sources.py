from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import SourceKind
from app.db.models import Source


async def get_or_create_source(
    session: AsyncSession,
    kind: SourceKind,
    name: str,
    *,
    config: dict[str, Any] | None = None,
    enabled: bool = True,
) -> Source:
    """Find the source row for (kind, name), creating it if missing. Safe under concurrency."""
    await session.execute(
        insert(Source)
        .values(kind=kind, name=name, config=config or {}, enabled=enabled)
        .on_conflict_do_nothing(constraint="uq_source_kind_name")
    )
    return (
        await session.execute(select(Source).where(Source.kind == kind, Source.name == name))
    ).scalar_one()
