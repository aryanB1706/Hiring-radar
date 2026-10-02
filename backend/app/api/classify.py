"""Job classification endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Lead, Post
from app.db.session import get_db
from app.llm.classifier import ClassificationError, classify_signal
from app.services.jobs import save_classification

router = APIRouter(prefix="/api", tags=["classification"])


class ClassificationResponse(BaseModel):
    """Saved classification for one signal."""

    signal_id: uuid.UUID
    lead_id: uuid.UUID
    is_hiring: bool
    company_name: str | None
    job_title: str | None
    skills: list[str]
    experience_level: str | None
    job_type: str | None
    location: str | None
    application_url: str | None
    confidence: float
    status: str


class PendingClassificationResponse(BaseModel):
    """Summary of a batch classification run."""

    processed: int
    hiring: int
    rejected: int


def _response(post: Post, lead: Lead) -> ClassificationResponse:
    return ClassificationResponse(
        signal_id=post.id,
        lead_id=lead.id,
        is_hiring=bool(lead.is_hiring),
        company_name=lead.company_name,
        job_title=lead.role_title,
        skills=lead.skills,
        experience_level=lead.seniority,
        job_type=lead.job_type,
        location=lead.location,
        application_url=lead.application_url,
        confidence=lead.confidence,
        status=lead.status.value,
    )


@router.post("/classify/pending", response_model=PendingClassificationResponse)
def classify_pending(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> PendingClassificationResponse:
    """Classify collected signals that do not have a lead yet."""
    posts = db.scalars(
        select(Post)
        .options(joinedload(Post.source))
        .outerjoin(Lead, Lead.post_id == Post.id)
        .where(Lead.id.is_(None))
        .order_by(Post.fetched_at.desc())
        .limit(limit)
    ).all()

    hiring = 0
    rejected = 0

    for post in posts:
        try:
            result = classify_signal(post)
        except ClassificationError:
            continue

        save_classification(db, post, result)
        if result.is_hiring:
            hiring += 1
        else:
            rejected += 1

    return PendingClassificationResponse(
        processed=hiring + rejected,
        hiring=hiring,
        rejected=rejected,
    )


@router.post("/classify/{signal_id}", response_model=ClassificationResponse)
def classify_one(
    signal_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ClassificationResponse:
    """Classify one collected signal and save the result."""
    post = db.scalar(select(Post).options(joinedload(Post.source)).where(Post.id == signal_id))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signal not found")

    try:
        result = classify_signal(post)
    except ClassificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    lead = save_classification(db, post, result)
    return _response(post, lead)
