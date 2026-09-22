from dataclasses import dataclass, field

import structlog
from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.classifier.service import ClassifierService
from app.db.enums import ActorType
from app.db.models import AuditEvent, Lead, Post

log = structlog.get_logger()

AUDIT_ACTION = "classify_post"
MAX_ATTEMPTS = 3  # a post that failed this many times is left alone until someone looks at it


@dataclass
class BatchSummary:
    selected: int = 0
    classified: int = 0
    failed: int = 0
    prefiltered: int = 0
    llm_calls: int = 0
    flagged: int = 0
    duplicates_linked: int = 0
    leads: list[Lead] = field(default_factory=list)  # for display; not part of the counts


async def pending_posts(session: AsyncSession, limit: int) -> list[Post]:
    """Posts with no lead yet, oldest first (so the earliest copy of a job becomes the original),
    skipping posts that already failed MAX_ATTEMPTS times."""
    failures = (
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.action == AUDIT_ACTION,
            AuditEvent.outcome == "error",
            AuditEvent.target_id == cast(Post.id, Text),
        )
        .scalar_subquery()
    )
    stmt = (
        select(Post)
        .outerjoin(Lead, Lead.post_id == Post.id)
        .where(Lead.id.is_(None), failures < MAX_ATTEMPTS)
        .order_by(func.coalesce(Post.posted_at, Post.fetched_at), Post.id)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars())


async def classify_pending(
    session: AsyncSession, service: ClassifierService, batch_size: int
) -> BatchSummary:
    """Classify up to batch_size posts. One bad post never stops the batch: its error goes to the
    audit log and we move on."""
    summary = BatchSummary()
    posts = await pending_posts(session, batch_size)
    summary.selected = len(posts)
    for post in posts:
        try:
            async with session.begin_nested():  # a failure rolls back only this post's work
                lead = await service.classify(post)
            await session.commit()
        except Exception as exc:  # noqa: BLE001 - the batch must survive any single failure
            log.warning("classify_failed", post_id=str(post.id), error=repr(exc))
            summary.failed += 1
            session.add(
                AuditEvent(
                    actor_type=ActorType.SYSTEM,
                    actor_id="classifier",
                    action=AUDIT_ACTION,
                    target_type="post",
                    target_id=str(post.id),
                    outcome="error",
                    reason=repr(exc)[:500],
                )
            )
            await session.commit()
            continue
        summary.classified += 1
        summary.leads.append(lead)
    stats = service.stats
    summary.prefiltered = stats.prefiltered
    summary.llm_calls = stats.llm_calls
    summary.flagged = stats.flagged
    summary.duplicates_linked = stats.duplicates_linked
    log.info(
        "classify_batch_done",
        **{k: v for k, v in summary.__dict__.items() if k != "leads"},
        prefilter_saved_llm_calls=stats.prefiltered,
    )
    return summary
