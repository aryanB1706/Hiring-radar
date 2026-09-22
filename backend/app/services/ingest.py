import uuid
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import RawPost, SourceAdapter
from app.core.text import MAX_TEXT_CHARS, clean_text, content_hash
from app.db.models import Post

log = structlog.get_logger()


@dataclass
class IngestCounts:
    fetched: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_empty: int = 0


class IngestService:
    """Stores posts idempotently. Running it twice over the same data inserts nothing new.

    A post is skipped as a duplicate if (source, external_id) already exists (database unique
    constraint + ON CONFLICT DO NOTHING) or if ANY existing post, from any source, has the same
    content hash. The caller owns the session; progress is committed every `batch_size` posts.
    """

    def __init__(self, session: AsyncSession, *, batch_size: int = 100) -> None:
        self._session = session
        self._batch_size = batch_size

    async def ingest(
        self, source_id: uuid.UUID, adapter: SourceAdapter, since: datetime | None = None
    ) -> IngestCounts:
        return await self.ingest_posts(source_id, adapter.fetch(since))

    async def ingest_posts(
        self, source_id: uuid.UUID, posts: AsyncIterable[RawPost] | list[RawPost]
    ) -> IngestCounts:
        counts = IngestCounts()
        async for raw in _aiter(posts):
            counts.fetched += 1
            await self._store(source_id, raw, counts)
            if counts.fetched % self._batch_size == 0:
                await self._session.commit()
        await self._session.commit()
        log.info("ingest_done", source_id=str(source_id), **counts.__dict__)
        return counts

    async def _store(self, source_id: uuid.UUID, raw: RawPost, counts: IngestCounts) -> None:
        text = clean_text(raw.raw_text)[:MAX_TEXT_CHARS]
        if not text:
            counts.skipped_empty += 1
            return
        digest = content_hash(text)
        seen = await self._session.execute(select(Post.id).where(Post.content_hash == digest))
        if seen.first() is not None:
            counts.skipped_duplicate += 1
            return
        inserted = await self._session.execute(
            insert(Post)
            .values(
                source_id=source_id,
                external_id=raw.external_id,
                url=raw.url,
                author_handle=raw.author_handle,
                raw_text=text,
                content_hash=digest,
                posted_at=raw.posted_at,
            )
            .on_conflict_do_nothing(constraint="uq_post_source_id_external_id")
            .returning(Post.id)
        )
        if inserted.first() is None:
            counts.skipped_duplicate += 1
        else:
            counts.inserted += 1


async def _aiter(posts: AsyncIterable[RawPost] | list[RawPost]) -> AsyncIterator[RawPost]:
    if isinstance(posts, list):
        for post in posts:
            yield post
    else:
        async for post in posts:
            yield post
