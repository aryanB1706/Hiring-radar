import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.collectors.base import SourceAdapter
from app.collectors.errors import SourceNotEnabledError
from app.collectors.http import PoliteHttpClient
from app.collectors.registry import POLLABLE_KINDS, build_adapter
from app.core.config import Settings
from app.db.enums import SourceKind
from app.db.models import Post, Source
from app.db.session import make_session_factory
from app.services.ingest import IngestCounts, IngestService
from app.services.sources import get_or_create_source

# Re-read the last day before the newest stored post, so a late-arriving post is not missed.
# Duplicates are harmless: ingestion is idempotent.
OVERLAP = timedelta(days=1)

# Sources the CLI can create on demand: name, initial config, enabled.
DEFAULT_SOURCES: dict[str, tuple[SourceKind, str, dict[str, Any], bool]] = {
    "hn": (SourceKind.HN, "hn-who-is-hiring", {"threads": ["hiring"]}, True),
    "reddit": (SourceKind.REDDIT, "reddit", {}, True),
    "rss": (SourceKind.RSS, "rss-default", {}, True),
    "linkedin": (SourceKind.LINKEDIN_USER_CAPTURE, "linkedin-user-capture", {}, False),
}


async def incremental_since(session: AsyncSession, source_id: uuid.UUID) -> datetime | None:
    newest = (
        await session.execute(select(func.max(Post.posted_at)).where(Post.source_id == source_id))
    ).scalar_one()
    return None if newest is None else newest.astimezone(UTC) - OVERLAP


async def ingest_source_row(
    session: AsyncSession, source: Source, adapter: SourceAdapter, *, full: bool = False
) -> IngestCounts:
    """Run one adapter for one source row. `full` ignores the incremental cut-off."""
    if adapter.enabled and not source.enabled:
        raise SourceNotEnabledError(f"source {source.name!r} is disabled in the database")
    since = None if full else await incremental_since(session, source.id)
    return await IngestService(session).ingest(source.id, adapter, since)


async def pollable_source_ids(session: AsyncSession) -> list[uuid.UUID]:
    rows = await session.execute(
        select(Source.id).where(Source.enabled.is_(True), Source.kind.in_(POLLABLE_KINDS))
    )
    return list(rows.scalars())


@asynccontextmanager
async def runtime(
    settings: Settings,
) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], PoliteHttpClient]]:
    """A fresh engine + HTTP client for one job (Celery tasks run in their own event loop)."""
    engine = create_async_engine(settings.database_url)
    http = PoliteHttpClient(
        settings.http_user_agent,
        timeout=settings.http_timeout_seconds,
        min_delay=settings.http_min_delay_seconds,
    )
    try:
        yield make_session_factory(engine), http
    finally:
        await http.aclose()
        await engine.dispose()


async def run_ingest(
    source_id: uuid.UUID, settings: Settings, *, full: bool = False
) -> IngestCounts:
    async with runtime(settings) as (session_factory, http), session_factory() as session:
        source = await session.get(Source, source_id)
        if source is None:
            raise LookupError(f"source {source_id} not found")
        adapter = build_adapter(source, settings, http)
        return await ingest_source_row(session, source, adapter, full=full)


async def run_ingest_by_name(
    name: str, settings: Settings, *, feeds: list[str] | None = None, full: bool = False
) -> IngestCounts:
    """CLI entry: find or create the default source called `name` (hn, reddit, rss, linkedin)."""
    kind, source_name, config, enabled = DEFAULT_SOURCES[name]
    async with runtime(settings) as (session_factory, _), session_factory() as session:
        source = await get_or_create_source(
            session, kind, source_name, config=config, enabled=enabled
        )
        if feeds:
            source.config = {
                **source.config,
                "feeds": sorted({*source.config.get("feeds", []), *feeds}),
            }
        await session.commit()
        source_id = source.id
    return await run_ingest(source_id, settings, full=full)
