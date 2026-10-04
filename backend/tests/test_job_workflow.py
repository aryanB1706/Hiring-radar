"""Tests for the LangGraph hiring workflow."""

import uuid
from contextlib import contextmanager

from sqlalchemy import select

from app.db.enums import LeadStatus, SourceKind
from app.db.models import Lead, Post, Source
from app.llm.classifier import ClassificationError, JobClassification
from app.workflows.job_workflow import (
    MAX_STEPS,
    classify_node,
    run_job_workflow,
)


@contextmanager
def session_scope(db_session):
    """Yield the test session without closing it."""
    yield db_session


def make_post(
    db_session,
    *,
    title: str = "Acme is hiring a Senior Python Engineer",
    content: str = "Acme is hiring. Apply at https://acme.example/jobs/1",
    url: str | None = None,
) -> Post:
    """Create a source and post in the test transaction."""
    source = Source(kind=SourceKind.HN, name="Workflow Test HN", enabled=True, config={})
    db_session.add(source)
    db_session.flush()

    post = Post(
        source_id=source.id,
        external_id=uuid.uuid4().hex,
        title=title,
        url=url or f"https://acme.example/jobs/{uuid.uuid4().hex}",
        raw_text=content,
        content_hash=uuid.uuid4().hex,
    )
    db_session.add(post)
    db_session.flush()
    return post


def hiring_result() -> JobClassification:
    """Build a complete hiring classification."""
    return JobClassification(
        is_hiring=True,
        company_name="Acme",
        job_title="Senior Python Engineer",
        skills=["Python", "FastAPI"],
        experience_level="Senior",
        job_type="full_time",
        location="Remote",
        application_url="https://acme.example/jobs/1",
        confidence=0.95,
    )


def test_workflow_saves_qualified_job(db_session, monkeypatch) -> None:
    """A genuine hiring signal goes through all four nodes and is saved."""
    post = make_post(db_session)
    indexed = {}

    monkeypatch.setattr(
        "app.workflows.job_workflow._session_scope",
        lambda: session_scope(db_session),
    )
    monkeypatch.setattr(
        "app.workflows.job_workflow.classify_signal",
        lambda post: hiring_result(),
    )
    monkeypatch.setattr(
        "app.workflows.job_workflow.index_job",
        lambda db, lead, result: indexed.update({"lead_id": lead.id}),
    )

    state = run_job_workflow(post.id)

    assert state["status"] == "saved"
    assert state["step_count"] == 4
    assert state["is_hiring"] is True
    assert state["company"] == "Acme"
    assert state["role"] == "Senior Python Engineer"
    assert state["skills"] == ["Python", "FastAPI"]
    assert state["job_type"] == "full_time"
    assert state["qualification_score"] >= 0.60
    assert state["errors"] == []

    lead = db_session.scalar(select(Lead).where(Lead.post_id == post.id))
    assert lead is not None
    assert lead.status == LeadStatus.QUALIFIED
    assert lead.score == state["qualification_score"]
    assert lead.company_name == "Acme"
    assert indexed["lead_id"] == lead.id


def test_workflow_ends_for_non_hiring_post(db_session, monkeypatch) -> None:
    """A tech discussion ends after classify_node without creating a lead."""
    post = make_post(
        db_session,
        title="Why Python is popular for data science",
        content="A discussion about Python libraries. No job is mentioned.",
    )

    monkeypatch.setattr(
        "app.workflows.job_workflow._session_scope",
        lambda: session_scope(db_session),
    )
    monkeypatch.setattr(
        "app.workflows.job_workflow.classify_signal",
        lambda post: JobClassification(is_hiring=False, confidence=0.9),
    )

    state = run_job_workflow(post.id)

    assert state["status"] == "rejected"
    assert state["is_hiring"] is False
    assert state["step_count"] == 1
    assert state["errors"] == []
    assert db_session.scalar(select(Lead).where(Lead.post_id == post.id)) is None


def test_workflow_ends_when_job_does_not_qualify(db_session, monkeypatch) -> None:
    """A hiring post with too little information stops before save_job_node."""
    post = make_post(db_session)
    result = JobClassification(is_hiring=True, confidence=0.2)

    monkeypatch.setattr(
        "app.workflows.job_workflow._session_scope",
        lambda: session_scope(db_session),
    )
    monkeypatch.setattr(
        "app.workflows.job_workflow.classify_signal",
        lambda post: result,
    )

    state = run_job_workflow(post.id)

    assert state["status"] == "needs_human"
    assert state["qualification_score"] < 0.60
    assert state["step_count"] == 3
    assert db_session.scalar(select(Lead).where(Lead.post_id == post.id)) is None


def test_workflow_retries_temporary_llm_failure(db_session, monkeypatch) -> None:
    """Temporary classifier failures are retried before succeeding."""
    post = make_post(db_session)
    calls = {"count": 0}

    def flaky_classifier(post):
        calls["count"] += 1
        if calls["count"] < 3:
            raise ClassificationError("temporary Groq failure")
        return hiring_result()

    monkeypatch.setattr(
        "app.workflows.job_workflow._session_scope",
        lambda: session_scope(db_session),
    )
    monkeypatch.setattr(
        "app.workflows.job_workflow.classify_signal",
        flaky_classifier,
    )
    monkeypatch.setattr("app.workflows.job_workflow.time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        "app.workflows.job_workflow.index_job",
        lambda db, lead, result: None,
    )

    state = run_job_workflow(post.id)

    assert state["status"] == "saved"
    assert calls["count"] == 3


def test_workflow_returns_error_after_retry_exhaustion(db_session, monkeypatch) -> None:
    """A persistent classifier failure stops the workflow with an error."""
    post = make_post(db_session)
    calls = {"count": 0}

    def failing_classifier(post):
        calls["count"] += 1
        raise ClassificationError("Groq is unavailable")

    monkeypatch.setattr(
        "app.workflows.job_workflow._session_scope",
        lambda: session_scope(db_session),
    )
    monkeypatch.setattr(
        "app.workflows.job_workflow.classify_signal",
        failing_classifier,
    )
    monkeypatch.setattr("app.workflows.job_workflow.time.sleep", lambda seconds: None)

    state = run_job_workflow(post.id)

    assert state["status"] == "error"
    assert state["step_count"] == 1
    assert "Groq is unavailable" in state["errors"]
    assert calls["count"] == 3
    assert db_session.scalar(select(Lead).where(Lead.post_id == post.id)) is None


def test_workflow_handles_unknown_signal(db_session, monkeypatch) -> None:
    """An unknown signal id stops with a clear error."""
    monkeypatch.setattr(
        "app.workflows.job_workflow._session_scope",
        lambda: session_scope(db_session),
    )

    state = run_job_workflow(uuid.uuid4())

    assert state["status"] == "error"
    assert "Signal not found" in state["errors"]
    assert state["step_count"] == 1


def test_node_stops_at_max_steps() -> None:
    """The step guard prevents the workflow from running forever."""
    state = classify_node(
        {
            "signal_id": str(uuid.uuid4()),
            "step_count": MAX_STEPS,
            "errors": [],
        }
    )

    assert state["status"] == "error"
    assert state["step_count"] == MAX_STEPS
    assert state["errors"] == ["Maximum workflow steps reached"]
