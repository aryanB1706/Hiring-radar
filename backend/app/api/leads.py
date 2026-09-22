import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.classifier.service import FLAGS_KIND
from app.db.enums import LeadStatus, LeadType
from app.db.models import Enrichment, Lead, Party, Post, Source
from app.db.session import get_session
from app.schemas.lead import LeadDetail, LeadOut, LeadPage, PostSummary

router = APIRouter(prefix="/leads", tags=["leads"])

Session = Annotated[AsyncSession, Depends(get_session)]

_BASE = (
    select(Lead, Post, Source.kind, Party.display_name)
    .join(Post, Post.id == Lead.post_id)
    .join(Source, Source.id == Post.source_id)
    .outerjoin(Party, Party.id == Lead.party_id)
)


def _lead_fields(
    lead: Lead, post: Post, source_kind: object, company: str | None
) -> dict[str, object]:
    return {
        "id": lead.id,
        "lead_type": lead.lead_type,
        "status": lead.status,
        "confidence": lead.confidence,
        "role_title": lead.role_title,
        "company_name": company,
        "skills": lead.skills,
        "seniority": lead.seniority,
        "location": lead.location,
        "is_remote": lead.is_remote,
        "budget_text": lead.budget_text,
        "budget_min": None if lead.budget_min is None else float(lead.budget_min),
        "budget_max": None if lead.budget_max is None else float(lead.budget_max),
        "currency": lead.currency,
        "urgency": lead.urgency,
        "contact_method": lead.contact_method,
        "evidence_quote": lead.evidence_quote,
        "score": lead.score,
        "scam_risk": lead.scam_risk,
        "duplicate_of_lead_id": lead.duplicate_of_lead_id,
        "classified_at": lead.classified_at,
        "post": PostSummary(
            id=post.id,
            url=post.url,
            author_handle=post.author_handle,
            posted_at=post.posted_at,
            source_kind=getattr(source_kind, "value", str(source_kind)),
        ),
    }


@router.get("", response_model=LeadPage)
async def list_leads(
    session: Session,
    lead_type: LeadType | None = None,
    status: LeadStatus | None = None,
    is_remote: bool | None = None,
    skill: str | None = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    include_duplicates: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LeadPage:
    conditions = []
    if lead_type is not None:
        conditions.append(Lead.lead_type == lead_type)
    if status is not None:
        conditions.append(Lead.status == status)
    if is_remote is not None:
        conditions.append(Lead.is_remote == is_remote)
    if skill:
        conditions.append(Lead.skills.contains([skill.strip().lower()]))
    if min_confidence is not None:
        conditions.append(Lead.confidence >= min_confidence)
    if not include_duplicates:
        conditions.append(Lead.duplicate_of_lead_id.is_(None))

    total = (
        await session.execute(select(func.count()).select_from(Lead).where(*conditions))
    ).scalar_one()
    rows = await session.execute(
        _BASE.where(*conditions)
        .order_by(Lead.score.desc().nulls_last(), Lead.classified_at.desc(), Lead.id)
        .limit(limit)
        .offset(offset)
    )
    items = [LeadOut(**_lead_fields(*row)) for row in rows.all()]
    return LeadPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{lead_id}", response_model=LeadDetail)
async def get_lead(lead_id: uuid.UUID, session: Session) -> LeadDetail:
    row = (await session.execute(_BASE.where(Lead.id == lead_id))).first()
    if row is None:
        raise HTTPException(404, "lead not found")
    lead, post, _, _ = row
    flag_rows = await session.execute(
        select(Enrichment.data).where(Enrichment.lead_id == lead.id, Enrichment.kind == FLAGS_KIND)
    )
    flags = [flag for data in flag_rows.scalars() for flag in data.get("flags", [])]
    return LeadDetail(**_lead_fields(*row), raw_text=post.raw_text, flags=flags)
