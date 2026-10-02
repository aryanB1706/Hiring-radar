"""Tests for job classification API endpoints."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.enums import SourceKind
from app.db.models import Lead, Post, Source
from app.db.session import get_db
from app.llm.classifier import ClassificationError, JobClassification


def make_post(
    db_session,
    *,
    external_id: str,
    title: str,
    content: str,
    url: str,
) -> Post:
    """Create a source and post in the test transaction."""
    source = db_session.scalar(select(Source).where(Source.name == "Classification Test HN"))
    if source is None:
        source = Source(
            kind=SourceKind.HN,
            name="Classification Test HN",
            enabled=True,
            config={},
        )
        db_session.add(source)
        db_session.flush()

    post = Post(
        source_id=source.id,
        external_id=external_id,
        title=title,
        url=url,
        raw_text=content,
        content_hash=uuid.uuid4().hex,
    )
    db_session.add(post)
    db_session.flush()
    return post


def hiring_result() -> JobClassification:
    """Build a complete hiring classification for tests."""
    return JobClassification(
        is_hiring=True,
        company_name="Acme",
        job_title="Python Engineer",
        skills=["Python"],
        experience_level="Senior",
        job_type="full_time",
        location="Remote",
        application_url="https://acme.example/jobs/1",
        confidence=0.95,
    )


def test_classify_one_endpoint(app, client: TestClient, db_session, monkeypatch) -> None:
    """The single-signal endpoint saves and returns a lead."""
    post = make_post(
        db_session,
        external_id="classify-1",
        title="Acme is hiring a Python Engineer",
        content="Acme is hiring. Apply at https://acme.example/jobs/1",
        url="https://acme.example/jobs/1",
    )
    app.dependency_overrides[get_db] = lambda: db_session
    monkeypatch.setattr("app.api.classify.classify_signal", lambda post: hiring_result())

    try:
        response = client.post(f"/api/classify/{post.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["signal_id"] == str(post.id)
        assert body["is_hiring"] is True
        assert body["company_name"] == "Acme"
        assert body["job_title"] == "Python Engineer"
        assert body["skills"] == ["Python"]
        assert body["job_type"] == "full_time"
        assert body["application_url"] == "https://acme.example/jobs/1"
        assert body["status"] == "qualified"
    finally:
        app.dependency_overrides.clear()


def test_classify_pending_endpoint(app, client: TestClient, db_session, monkeypatch) -> None:
    """The pending endpoint classifies each unprocessed signal once."""
    db_session.execute(delete(Post))
    first = make_post(
        db_session,
        external_id="pending-1",
        title="Acme is hiring a Python Engineer",
        content="Acme is hiring. Apply at https://acme.example/jobs/1",
        url="https://acme.example/jobs/1",
    )
    second = make_post(
        db_session,
        external_id="pending-2",
        title="Beta is hiring a Django Developer",
        content="Beta is hiring. Apply at https://beta.example/jobs/2",
        url="https://beta.example/jobs/2",
    )
    app.dependency_overrides[get_db] = lambda: db_session
    monkeypatch.setattr("app.api.classify.classify_signal", lambda post: hiring_result())

    try:
        response = client.post("/api/classify/pending?limit=10")
        assert response.status_code == 200
        assert response.json() == {"processed": 2, "hiring": 2, "rejected": 0}

        leads = db_session.scalars(select(Lead)).all()
        assert {lead.post_id for lead in leads} == {first.id, second.id}

        again = client.post("/api/classify/pending?limit=10")
        assert again.json() == {"processed": 0, "hiring": 0, "rejected": 0}
    finally:
        app.dependency_overrides.clear()


def test_classify_one_returns_404(app, client: TestClient, db_session) -> None:
    """An unknown signal id returns 404."""
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        response = client.post(f"/api/classify/{uuid.uuid4()}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_classify_one_returns_502_on_classification_error(
    app, client: TestClient, db_session, monkeypatch
) -> None:
    """A classification failure is returned as 502."""
    post = make_post(
        db_session,
        external_id="classify-error",
        title="Acme is hiring",
        content="Acme is hiring.",
        url="https://acme.example/jobs/error",
    )
    app.dependency_overrides[get_db] = lambda: db_session

    def fail(post):
        raise ClassificationError("Groq classification failed")

    monkeypatch.setattr("app.api.classify.classify_signal", fail)

    try:
        response = client.post(f"/api/classify/{post.id}")
        assert response.status_code == 502
    finally:
        app.dependency_overrides.clear()
