"""Job classification persistence helpers."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import LeadStatus, LeadType
from app.db.models import Lead, Post
from app.llm.classifier import JobClassification


def save_classification(
    db: Session,
    post: Post,
    result: JobClassification,
    score: float | None = None,
) -> Lead:
    """Create or update the lead row for one classified signal."""
    lead = db.scalar(select(Lead).where(Lead.post_id == post.id))
    if lead is None:
        lead = Lead(post_id=post.id, lead_type=LeadType.NOT_A_LEAD)
        db.add(lead)

    lead.is_hiring = result.is_hiring
    lead.lead_type = _lead_type(result)
    lead.company_name = result.company_name
    lead.company_key = result.company_name.lower() if result.company_name else None
    lead.role_title = result.job_title
    lead.skills = result.skills
    lead.seniority = result.experience_level
    lead.job_type = result.job_type
    lead.location = result.location
    lead.application_url = _application_url(result, post)
    lead.confidence = result.confidence
    if score is not None:
        lead.score = score
    lead.status = LeadStatus.QUALIFIED if result.is_hiring else LeadStatus.REJECTED
    lead.classified_at = datetime.now(UTC)
    lead.prompt_version = "v1"

    db.commit()
    db.refresh(lead)
    return lead


def _lead_type(result: JobClassification) -> LeadType:
    """Map the extracted job type to the existing lead type enum."""
    if not result.is_hiring:
        return LeadType.NOT_A_LEAD
    if result.job_type == "internship":
        return LeadType.INTERNSHIP
    if result.job_type == "contract":
        return LeadType.FREELANCE_GIG
    return LeadType.HIRING


def _application_url(result: JobClassification, post: Post) -> str | None:
    """Keep only a URL that appears in the post, otherwise use the source URL."""
    if not result.is_hiring:
        return None
    if result.application_url:
        searchable = f"{post.title or ''}\n{post.raw_text or ''}"
        if result.application_url in searchable:
            return result.application_url
    return post.url
