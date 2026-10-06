"""Job discovery and recommendation endpoints."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import JobSeeker, Lead, Post
from app.db.session import get_db
from app.services.job_matching import JobSeekerProfile, find_matching_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobSourceResponse(BaseModel):
    """Source information for a discovered job."""

    name: str
    kind: str
    url: str


class JobResponse(BaseModel):
    """A discovered job with its original application URL and verification state."""

    id: uuid.UUID
    company: str | None
    role: str | None
    skills: list[str]
    experience_level: str | None
    location: str | None
    job_type: str | None
    is_remote: bool | None
    source: JobSourceResponse
    application_url: str | None
    is_verified: bool
    is_expired: bool
    verification_status: str
    lead_status: str
    posted_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class RecommendedJobResponse(JobResponse):
    """A job recommendation with semantic and compatibility scores."""

    semantic_similarity: float
    role_compatibility: float
    experience_compatibility: float
    match_score: float


class JobListResponse(BaseModel):
    """Paginated job listing."""

    items: list[JobResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


def _job_response(lead: Lead) -> JobResponse:
    post = lead.post
    source = post.source if post is not None else None
    now = datetime.now(UTC)
    is_expired = bool(lead.expires_at is not None and lead.expires_at <= now)
    is_verified = bool(lead.evidence_verified)
    if is_expired:
        verification_status = "expired"
    elif is_verified:
        verification_status = "verified"
    else:
        verification_status = "unverified"

    return JobResponse(
        id=lead.id,
        company=lead.company_name,
        role=lead.role_title,
        skills=lead.skills or [],
        experience_level=lead.seniority,
        location=lead.location,
        job_type=lead.job_type,
        is_remote=lead.is_remote,
        source=JobSourceResponse(
            name=source.name if source is not None else "unknown",
            kind=source.kind.value if source is not None else "unknown",
            url=post.url if post is not None else "",
        ),
        application_url=lead.application_url,
        is_verified=is_verified,
        is_expired=is_expired,
        verification_status=verification_status,
        lead_status=lead.status.value,
        posted_at=post.posted_at if post is not None else None,
        expires_at=lead.expires_at,
        created_at=lead.created_at,
    )


@router.get("", response_model=JobListResponse)
def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> JobListResponse:
    """List hiring jobs with simple pagination."""
    total = (
        db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(Lead.is_hiring.is_(True))
        )
        or 0
    )
    leads = db.scalars(
        select(Lead)
        .options(joinedload(Lead.post).joinedload(Post.source))
        .where(Lead.is_hiring.is_(True))
        .order_by(Lead.created_at.desc(), Lead.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return JobListResponse(
        items=[_job_response(lead) for lead in leads],
        page=page,
        page_size=page_size,
        total=total,
        has_next=page * page_size < total,
    )


@router.get("/recommended/{user_id}", response_model=list[RecommendedJobResponse])
def recommended_jobs(
    user_id: uuid.UUID,
    limit: int = Query(10, ge=1, le=50),
    similarity_threshold: float | None = Query(None, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> list[RecommendedJobResponse]:
    """Return semantic job recommendations for one job seeker."""
    user = db.get(JobSeeker, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    profile = JobSeekerProfile(
        skills=user.skills or [],
        preferred_roles=user.preferred_roles or [],
        experience_level=user.experience_level,
        preferences=(
            f"Preferred job type: {user.preferred_job_type}"
            if user.preferred_job_type
            else None
        ),
    )
    matches = find_matching_jobs(
        db,
        profile,
        similarity_threshold=similarity_threshold,
        limit=limit,
        candidate_limit=max(limit * 5, 50),
    )
    if not matches:
        return []

    lead_ids = [uuid.UUID(match.lead_id) for match in matches]
    leads = db.scalars(
        select(Lead)
        .options(joinedload(Lead.post).joinedload(Post.source))
        .where(Lead.id.in_(lead_ids))
    ).all()
    leads_by_id = {lead.id: lead for lead in leads}

    results: list[RecommendedJobResponse] = []
    for match in matches:
        lead = leads_by_id.get(uuid.UUID(match.lead_id))
        if lead is None:
            continue
        job = _job_response(lead)
        results.append(
            RecommendedJobResponse(
                **job.model_dump(),
                semantic_similarity=match.semantic_similarity,
                role_compatibility=match.role_compatibility,
                experience_compatibility=match.experience_compatibility,
                match_score=match.match_score,
            )
        )
    return results


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> JobResponse:
    """Get one job by its lead id."""
    lead = db.scalar(
        select(Lead)
        .options(joinedload(Lead.post).joinedload(Post.source))
        .where(Lead.id == job_id, Lead.is_hiring.is_(True))
    )
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _job_response(lead)
