"""Tests for saving classified job leads."""

import uuid

from sqlalchemy import func, select

from app.db.enums import LeadStatus, LeadType, SourceKind
from app.db.models import Lead, Post, Source
from app.llm.classifier import JobClassification
from app.services.jobs import save_classification


def make_post(
    db_session,
    *,
    title: str = "Acme is hiring a Python Engineer",
    content: str = "Acme is hiring. Apply at https://acme.example/jobs/1",
    url: str = "https://acme.example/jobs/1",
) -> Post:
    """Create a source and post in the test transaction."""
    source = Source(kind=SourceKind.HN, name="Test Hacker News", enabled=True, config={})
    db_session.add(source)
    db_session.flush()

    post = Post(
        source_id=source.id,
        external_id=uuid.uuid4().hex,
        title=title,
        url=url,
        raw_text=content,
        content_hash=uuid.uuid4().hex,
    )
    db_session.add(post)
    db_session.flush()
    return post


def test_save_hiring_classification(db_session) -> None:
    """A hiring result is saved as a qualified lead."""
    post = make_post(db_session)
    result = JobClassification(
        is_hiring=True,
        company_name="Acme",
        job_title="Python Engineer",
        skills=["Python", "FastAPI"],
        experience_level="Senior",
        job_type="full_time",
        location="Remote",
        application_url="https://acme.example/jobs/1",
        confidence=0.92,
    )

    lead = save_classification(db_session, post, result)

    assert lead.is_hiring is True
    assert lead.lead_type == LeadType.HIRING
    assert lead.company_name == "Acme"
    assert lead.company_key == "acme"
    assert lead.role_title == "Python Engineer"
    assert lead.skills == ["Python", "FastAPI"]
    assert lead.seniority == "Senior"
    assert lead.job_type == "full_time"
    assert lead.location == "Remote"
    assert lead.application_url == "https://acme.example/jobs/1"
    assert lead.confidence == 0.92
    assert lead.status == LeadStatus.QUALIFIED
    assert lead.prompt_version == "v1"
    assert lead.classified_at is not None


def test_save_internship_classification(db_session) -> None:
    """An internship result uses the internship lead type."""
    post = make_post(db_session, title="Python Intern", url="https://example.com/intern")
    result = JobClassification(
        is_hiring=True,
        company_name="Acme",
        job_title="Python Intern",
        job_type="internship",
        confidence=0.8,
    )

    lead = save_classification(db_session, post, result)

    assert lead.lead_type == LeadType.INTERNSHIP
    assert lead.status == LeadStatus.QUALIFIED


def test_save_contract_classification(db_session) -> None:
    """A contract result uses the freelance gig lead type."""
    post = make_post(db_session, title="Contract Django Developer", url="https://example.com/gig")
    result = JobClassification(
        is_hiring=True,
        job_title="Django Developer",
        job_type="contract",
        confidence=0.8,
    )

    lead = save_classification(db_session, post, result)

    assert lead.lead_type == LeadType.FREELANCE_GIG
    assert lead.status == LeadStatus.QUALIFIED


def test_save_non_hiring_classification(db_session) -> None:
    """A non-hiring post is saved as rejected and has no application URL."""
    post = make_post(db_session, title="Python discussion", content="No job here.")
    result = JobClassification(is_hiring=False, confidence=0.7)

    lead = save_classification(db_session, post, result)

    assert lead.is_hiring is False
    assert lead.lead_type == LeadType.NOT_A_LEAD
    assert lead.status == LeadStatus.REJECTED
    assert lead.application_url is None


def test_application_url_must_exist_in_post(db_session) -> None:
    """An invented URL is replaced with the original source URL."""
    post = make_post(
        db_session,
        title="Acme is hiring",
        content="Acme is hiring a Python Engineer.",
        url="https://news.ycombinator.com/item?id=1",
    )
    result = JobClassification(
        is_hiring=True,
        company_name="Acme",
        job_title="Python Engineer",
        application_url="https://fake.example/apply",
        confidence=0.8,
    )

    lead = save_classification(db_session, post, result)

    assert lead.application_url == post.url


def test_reclassification_updates_existing_lead(db_session) -> None:
    """Classifying the same post twice updates one lead row."""
    post = make_post(db_session)
    first = JobClassification(
        is_hiring=True,
        company_name="Acme",
        job_title="Python Engineer",
        confidence=0.5,
    )
    second = JobClassification(
        is_hiring=True,
        company_name="Acme",
        job_title="Senior Python Engineer",
        confidence=0.9,
    )

    first_lead = save_classification(db_session, post, first)
    second_lead = save_classification(db_session, post, second)

    count = db_session.scalar(select(func.count()).select_from(Lead).where(Lead.post_id == post.id))
    assert count == 1
    assert first_lead.id == second_lead.id
    assert second_lead.role_title == "Senior Python Engineer"
    assert second_lead.confidence == 0.9
