import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import LeadType
from app.db.models import Lead, Post
from app.schemas.lead import LeadExtraction


def embedding_text(extraction: LeadExtraction) -> str:
    """The text we embed: the parts that make two posts 'the same job'."""
    parts = [
        extraction.role_title,
        ", ".join(extraction.skills) or None,
        extraction.company_name,
        extraction.location,
    ]
    return " | ".join(part for part in parts if part)


async def find_original(
    session: AsyncSession,
    embedding: list[float],
    *,
    post_time: dt.datetime,
    threshold: float,
) -> uuid.UUID | None:
    """The lead that a new lead with this embedding duplicates, or None.

    Equivalent SQL (`<=>` is pgvector's cosine DISTANCE: 0 = same direction, 2 = opposite):

        SELECT COALESCE(l.duplicate_of_lead_id, l.id), COALESCE(p.posted_at, p.fetched_at)
        FROM lead l JOIN post p ON p.id = l.post_id
        WHERE l.embedding IS NOT NULL
          AND l.lead_type <> 'not_a_lead'
          AND l.embedding <=> :new_embedding < :threshold
        ORDER BY COALESCE(p.posted_at, p.fetched_at), l.id
        LIMIT 1

    - Only real leads with an embedding are candidates; the distance filter keeps close matches.
    - ORDER BY age picks the OLDEST match, so every later copy points at the first one seen.
    - COALESCE(duplicate_of_lead_id, id) resolves a match that is itself a duplicate to its
      canonical lead, so links never form chains.
    - The new lead is not inserted yet, so it cannot match itself.
    A match newer than the new post is ignored: that link would point the wrong way in time.
    """
    when = func.coalesce(Post.posted_at, Post.fetched_at)
    row = (
        await session.execute(
            select(func.coalesce(Lead.duplicate_of_lead_id, Lead.id), when)
            .join(Post, Post.id == Lead.post_id)
            .where(
                Lead.embedding.is_not(None),
                Lead.lead_type != LeadType.NOT_A_LEAD,
                Lead.embedding.cosine_distance(embedding) < threshold,
            )
            .order_by(when, Lead.id)
            .limit(1)
        )
    ).first()
    if row is None or row[1] > post_time:
        return None
    return row[0]
