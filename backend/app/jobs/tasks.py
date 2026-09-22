import asyncio
import uuid
from dataclasses import asdict

import httpx

from app.core.config import get_settings
from app.jobs.celery_app import celery_app
from app.jobs.classify import run_classify_batch
from app.jobs.runner import pollable_source_ids, run_ingest, runtime


@celery_app.task(
    name="app.jobs.tasks.ingest_source",
    autoretry_for=(httpx.HTTPError,),  # network trouble only; policy/config errors are not retried
    retry_backoff=True,
    max_retries=3,
)
def ingest_source(source_id: str, full: bool = False) -> dict[str, int]:
    counts = asyncio.run(run_ingest(uuid.UUID(source_id), get_settings(), full=full))
    return asdict(counts)


@celery_app.task(name="app.jobs.tasks.ingest_all_sources")
def ingest_all_sources() -> list[str]:
    """Beat entry point: queue one ingest_source task per enabled, pollable source."""

    async def ids() -> list[uuid.UUID]:
        async with runtime(get_settings()) as (session_factory, _), session_factory() as session:
            return await pollable_source_ids(session)

    queued = [str(source_id) for source_id in asyncio.run(ids())]
    for source_id in queued:
        ingest_source.delay(source_id)
    return queued


@celery_app.task(name="app.jobs.tasks.classify_pending_posts")
def classify_pending_posts(batch_size: int = 50) -> dict[str, int]:
    """Classify posts that have no lead yet. Not on the beat schedule: it spends LLM quota, so
    it is triggered on purpose (CLI or `celery call`)."""
    summary = asyncio.run(run_classify_batch(get_settings(), batch_size))
    return {k: v for k, v in asdict(summary).items() if k != "leads"}
