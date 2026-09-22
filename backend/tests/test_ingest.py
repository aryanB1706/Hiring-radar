from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import RawPost, SourceAdapter
from app.collectors.disabled import LinkedInAdapter
from app.collectors.errors import DisabledSourceError, SourceNotEnabledError
from app.core.text import content_hash
from app.db.enums import SourceKind
from app.db.models import Post, Source
from app.jobs.runner import OVERLAP, incremental_since, ingest_source_row, pollable_source_ids
from app.services.ingest import IngestService
from app.services.sources import get_or_create_source
from tests.factories import make_source

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def raw(external_id: str, text: str, posted_at: datetime | None = NOW) -> RawPost:
    return RawPost(
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        author_handle="someone",
        raw_text=text,
        posted_at=posted_at,
    )


class ListAdapter(SourceAdapter):
    kind = SourceKind.HN

    def __init__(self, posts: list[RawPost]) -> None:
        self.posts = posts
        self.since_seen: list[datetime | None] = []

    async def fetch(self, since: datetime | None = None) -> AsyncIterator[RawPost]:
        self.since_seen.append(since)
        for post in self.posts:
            yield post


async def count_posts(session: AsyncSession, source: Source) -> int:
    stmt = select(func.count()).select_from(Post).where(Post.source_id == source.id)
    return (await session.execute(stmt)).scalar_one()


async def test_ingest_stores_cleaned_posts_with_hash(session: AsyncSession) -> None:
    source = await make_source(session)
    posts = [raw("1", "  Hiring   a Python dev \n\n\n\n remote  ")]
    counts = await IngestService(session).ingest_posts(source.id, posts)

    assert (counts.fetched, counts.inserted, counts.skipped_duplicate) == (1, 1, 0)
    row = (await session.execute(select(Post).where(Post.source_id == source.id))).scalar_one()
    assert row.raw_text == "Hiring a Python dev\n\nremote"
    assert row.content_hash == content_hash("hiring a python dev remote")
    assert (row.external_id, row.author_handle, row.posted_at) == ("1", "someone", NOW)


async def test_running_twice_inserts_nothing_the_second_time(session: AsyncSession) -> None:
    source = await make_source(session)
    adapter = ListAdapter([raw("1", "post one"), raw("2", "post two"), raw("3", "post three")])
    service = IngestService(session)

    first = await service.ingest(source.id, adapter)
    second = await service.ingest(source.id, adapter)

    assert (first.fetched, first.inserted, first.skipped_duplicate) == (3, 3, 0)
    assert (second.fetched, second.inserted, second.skipped_duplicate) == (3, 0, 3)
    assert await count_posts(session, source) == 3


async def test_same_external_id_with_new_text_hits_on_conflict_do_nothing(
    session: AsyncSession,
) -> None:
    source = await make_source(session)
    service = IngestService(session)
    await service.ingest_posts(source.id, [raw("1", "original text")])

    counts = await service.ingest_posts(source.id, [raw("1", "edited text")])

    assert (counts.inserted, counts.skipped_duplicate) == (0, 1)
    stored = await session.execute(select(Post.raw_text).where(Post.source_id == source.id))
    assert stored.scalar_one() == "original text"  # the first version is kept


async def test_same_content_from_another_source_is_skipped(session: AsyncSession) -> None:
    hn = await make_source(session)
    reddit = await make_source(session)
    service = IngestService(session)
    await service.ingest_posts(hn.id, [raw("a", "We are hiring a Python developer, remote")])

    counts = await service.ingest_posts(
        reddit.id, [raw("zzz", "WE ARE HIRING   a python developer,\nremote")]
    )

    assert (counts.inserted, counts.skipped_duplicate) == (0, 1)
    assert await count_posts(session, reddit) == 0


async def test_duplicates_inside_one_batch_are_caught(session: AsyncSession) -> None:
    source = await make_source(session)
    counts = await IngestService(session).ingest_posts(
        source.id, [raw("1", "same text"), raw("2", "Same  Text")]
    )
    assert (counts.fetched, counts.inserted, counts.skipped_duplicate) == (2, 1, 1)


async def test_empty_posts_are_skipped_and_counted(session: AsyncSession) -> None:
    source = await make_source(session)
    counts = await IngestService(session).ingest_posts(
        source.id, [raw("1", " \n\t "), raw("2", "ok")]
    )
    assert (counts.fetched, counts.inserted, counts.skipped_empty) == (2, 1, 1)


async def test_progress_is_committed_in_batches(session: AsyncSession) -> None:
    source = await make_source(session)
    posts = [raw(str(i), f"distinct post number {i}") for i in range(5)]
    counts = await IngestService(session, batch_size=2).ingest_posts(source.id, posts)
    assert counts.inserted == 5


async def test_get_or_create_source_is_idempotent(session: AsyncSession) -> None:
    first = await get_or_create_source(
        session, SourceKind.HN, "hn-test", config={"threads": ["hiring"]}
    )
    second = await get_or_create_source(session, SourceKind.HN, "hn-test")
    assert first.id == second.id
    assert second.config == {"threads": ["hiring"]}


# --- runner -----------------------------------------------------------------------------------


async def test_incremental_since_is_newest_post_minus_overlap(session: AsyncSession) -> None:
    source = await make_source(session)
    assert await incremental_since(session, source.id) is None  # nothing stored yet

    older = NOW - timedelta(days=3)
    await IngestService(session).ingest_posts(source.id, [raw("1", "a", older), raw("2", "b", NOW)])

    assert await incremental_since(session, source.id) == NOW - OVERLAP


async def test_full_run_ignores_the_cutoff(session: AsyncSession) -> None:
    source = await make_source(session)
    adapter = ListAdapter([raw("1", "a")])

    await ingest_source_row(session, source, adapter)
    await ingest_source_row(session, source, adapter)
    await ingest_source_row(session, source, adapter, full=True)

    assert adapter.since_seen == [None, NOW - OVERLAP, None]


async def test_a_source_switched_off_in_the_database_is_not_run(session: AsyncSession) -> None:
    source = await make_source(session)
    source.enabled = False
    with pytest.raises(SourceNotEnabledError):
        await ingest_source_row(session, source, ListAdapter([raw("1", "a")]))


async def test_linkedin_cannot_be_ingested_even_if_enabled_in_the_database(
    session: AsyncSession,
) -> None:
    source = await get_or_create_source(
        session, SourceKind.LINKEDIN_USER_CAPTURE, "li-test", enabled=True
    )
    with pytest.raises(DisabledSourceError):
        await ingest_source_row(session, source, LinkedInAdapter())


async def test_only_enabled_pollable_sources_are_scheduled(session: AsyncSession) -> None:
    on = await get_or_create_source(session, SourceKind.HN, "sched-on")
    off = await get_or_create_source(session, SourceKind.RSS, "sched-off", enabled=False)
    paste = await get_or_create_source(session, SourceKind.MANUAL_PASTE, "sched-paste")
    linkedin = await get_or_create_source(
        session, SourceKind.LINKEDIN_USER_CAPTURE, "sched-li", enabled=True
    )

    ids = set(await pollable_source_ids(session))

    assert on.id in ids
    assert not ({off.id, paste.id, linkedin.id} & ids)
