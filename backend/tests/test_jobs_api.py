"""Tests for job discovery and recommendation API endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.enums import LeadStatus, LeadType, SourceKind
from app.db.models import Lead, Post, Source
from app.db.session import get_db
from app.services.job_embeddings import embedding_literal


def vector(primary: float, secondary: float = 0.0) -> list[float]:
    return [primary, secondary] + [0.0] * 382


def make_job(
    db_session,
    *,
    company: str,
    role: str,
    skills: list[str],
    embedding: list[float] | None = None,
    source_name: str = "Test Jobs Feed",
    application_url: str | None = "https://acme.example/apply/1",
    evidence_verified: bool = False,
    expires_at: datetime | None = None,
    posted_at: datetime | None = None,
    created_at: datetime | None = None,
) -> Lead:
    suffix = uuid.uuid4().hex
    source = Source(
        kind=SourceKind.RSS,
        name=source_name,
        enabled=True,
        config={},
    )
    db_session.add(source)
    db_session.flush()

    post = Post(
        source_id=source.id,
        external_id=f"job-{suffix}",
        title=role,
        url=f"https://example.test/source/{suffix}",
        raw_text=f"{company} is hiring a {role}.",
        content_hash=suffix,
        posted_at=posted_at,
    )
    db_session.add(post)
    db_session.flush()

    lead = Lead(
        post_id=post.id,
        company_name=company,
        is_hiring=True,
        lead_type=LeadType.HIRING,
        role_title=role,
        skills=skills,
        seniority="mid",
        job_type="full_time",
        location="Remote",
        application_url=application_url,
        is_remote=True,
        confidence=0.9,
        status=LeadStatus.QUALIFIED,
        evidence_verified=evidence_verified,
        expires_at=expires_at,
    )
    if created_at is not None:
        lead.created_at = created_at
    db_session.add(lead)
    db_session.flush()

    if embedding is not None:
        db_session.execute(
            text(
                """
                INSERT INTO job_embedding (lead_id, content, content_hash, embedding)
                VALUES (:lead_id, :content, NULL, CAST(:embedding AS vector))
                """
            ),
            {
                "lead_id": lead.id,
                "content": f"{role} {' '.join(skills)}",
                "embedding": embedding_literal(embedding),
            },
        )
        db_session.flush()

    return lead


def test_list_jobs_paginates(app, client: TestClient, db_session) -> None:
    """The job list is paginated and ordered by newest first."""
    app.dependency_overrides[get_db] = lambda: db_session
    now = datetime.now(UTC)

    try:
        newest = make_job(
            db_session,
            company="Newest Co",
            role="Python Engineer",
            skills=["Python"],
            created_at=now + timedelta(seconds=2),
        )
        second = make_job(
            db_session,
            company="Second Co",
            role="React Engineer",
            skills=["React"],
            created_at=now + timedelta(seconds=1),
        )

        first_page = client.get("/api/jobs?page=1&page_size=1")
        assert first_page.status_code == 200
        body = first_page.json()
        assert body["page"] == 1
        assert body["page_size"] == 1
        assert body["total"] >= 2
        assert body["has_next"] is True
        assert len(body["items"]) == 1
        assert body["items"][0]["id"] == str(newest.id)
        assert body["items"][0]["company"] == "Newest Co"

        second_page = client.get("/api/jobs?page=2&page_size=1")
        assert second_page.status_code == 200
        assert second_page.json()["items"][0]["id"] == str(second.id)

        invalid_page = client.get("/api/jobs?page=0")
        assert invalid_page.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_get_job_preserves_urls_and_marks_verification(app, client: TestClient, db_session) -> None:
    """Job detail preserves application URLs and marks verified, unverified, and expired jobs."""
    app.dependency_overrides[get_db] = lambda: db_session
    now = datetime.now(UTC)

    try:
        expired = make_job(
            db_session,
            company="Expired Co",
            role="Python Engineer",
            skills=["Python", "FastAPI"],
            application_url="https://expired.example/original-application",
            evidence_verified=False,
            expires_at=now - timedelta(days=1),
        )
        verified = make_job(
            db_session,
            company="Verified Co",
            role="React Engineer",
            skills=["React", "TypeScript"],
            application_url="https://verified.example/original-application",
            evidence_verified=True,
            expires_at=now + timedelta(days=30),
        )
        unverified = make_job(
            db_session,
            company="Unverified Co",
            role="Data Engineer",
            skills=["SQL", "Python"],
            application_url="https://unverified.example/original-application",
            evidence_verified=False,
        )

        expired_body = client.get(f"/api/jobs/{expired.id}").json()
        assert expired_body["application_url"] == "https://expired.example/original-application"
        assert expired_body["source"]["url"] == expired.post.url
        assert expired_body["source"]["kind"] == "rss"
        assert expired_body["company"] == "Expired Co"
        assert expired_body["role"] == "Python Engineer"
        assert expired_body["skills"] == ["Python", "FastAPI"]
        assert expired_body["experience_level"] == "mid"
        assert expired_body["location"] == "Remote"
        assert expired_body["is_verified"] is False
        assert expired_body["is_expired"] is True
        assert expired_body["verification_status"] == "expired"

        verified_body = client.get(f"/api/jobs/{verified.id}").json()
        assert verified_body["is_verified"] is True
        assert verified_body["is_expired"] is False
        assert verified_body["verification_status"] == "verified"

        unverified_body = client.get(f"/api/jobs/{unverified.id}").json()
        assert unverified_body["is_verified"] is False
        assert unverified_body["is_expired"] is False
        assert unverified_body["verification_status"] == "unverified"
    finally:
        app.dependency_overrides.clear()


def test_recommended_jobs_returns_match_scores(
    app,
    client: TestClient,
    db_session,
    monkeypatch,
) -> None:
    """Recommendations use semantic matching and return scores with full job data."""
    app.dependency_overrides[get_db] = lambda: db_session
    now = datetime.now(UTC)

    try:
        python_job = make_job(
            db_session,
            company="PyCo",
            role="Python Backend Engineer",
            skills=["Python", "FastAPI", "PostgreSQL"],
            embedding=vector(1.0, 0.0),
            source_name="Python Jobs Feed",
            application_url="https://pyco.example/original-application",
            evidence_verified=True,
            expires_at=now + timedelta(days=30),
        )
        react_job = make_job(
            db_session,
            company="ReactCo",
            role="React Frontend Engineer",
            skills=["React", "TypeScript"],
            embedding=vector(0.2, 0.98),
            source_name="React Jobs Feed",
            application_url="https://reactco.example/original-application",
        )

        user = client.post(
            "/api/users",
            json={
                "name": "Alice",
                "skills": ["Python", "FastAPI"],
                "preferred_roles": ["Python Backend Engineer"],
                "experience_level": "mid",
                "preferred_job_type": "full_time",
            },
        ).json()

        monkeypatch.setattr(
            "app.services.job_matching.embed_text",
            lambda value: vector(1.0, 0.0),
        )
        response = client.get(
            f"/api/jobs/recommended/{user['id']}?limit=50&similarity_threshold=0"
        )
        assert response.status_code == 200
        items = {item["id"]: item for item in response.json()}

        assert str(python_job.id) in items
        assert str(react_job.id) in items
        python_match = items[str(python_job.id)]
        react_match = items[str(react_job.id)]
        assert python_match["match_score"] > react_match["match_score"]
        assert python_match["semantic_similarity"] == 1.0
        assert 0.0 <= react_match["semantic_similarity"] <= 1.0
        assert python_match["application_url"] == "https://pyco.example/original-application"
        assert python_match["company"] == "PyCo"
        assert python_match["role"] == "Python Backend Engineer"
        assert python_match["skills"] == ["Python", "FastAPI", "PostgreSQL"]
        assert python_match["experience_level"] == "mid"
        assert python_match["location"] == "Remote"
        assert python_match["source"]["name"] == "Python Jobs Feed"
        assert python_match["is_verified"] is True
        assert python_match["is_expired"] is False
    finally:
        app.dependency_overrides.clear()


def test_job_endpoints_return_404(app, client: TestClient, db_session) -> None:
    """Unknown job and user ids return 404."""
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        job_id = uuid.uuid4()
        user_id = uuid.uuid4()
        assert client.get(f"/api/jobs/{job_id}").status_code == 404
        assert client.get(f"/api/jobs/recommended/{user_id}").status_code == 404
    finally:
        app.dependency_overrides.clear()
