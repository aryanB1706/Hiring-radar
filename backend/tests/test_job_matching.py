"""Tests for profile-based semantic job matching."""

import uuid

import pytest

from app.services.job_matching import (
    JobSeekerProfile,
    find_matching_jobs,
    profile_embedding_text,
)


class FakeMappings:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class FakeResult:
    def __init__(self, rows) -> None:
        self.rows = rows

    def mappings(self) -> FakeMappings:
        return FakeMappings(self.rows)


class FakeSession:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.statements: list[str] = []
        self.params = {}

    def execute(self, statement, params):
        self.statements.append(str(statement))
        self.params = params
        return FakeResult(self.rows)


def job_row(
    role: str,
    skills: list[str],
    seniority: str | None,
    distance: float,
) -> dict:
    return {
        "lead_id": uuid.uuid4(),
        "company_name": "Acme",
        "role_title": role,
        "skills": skills,
        "seniority": seniority,
        "location": "Remote",
        "application_url": "https://acme.example/jobs/1",
        "distance": distance,
    }


def test_profile_embedding_text_includes_profile_fields() -> None:
    """Profiles are embedded using skills, roles, experience, and preferences."""
    profile = JobSeekerProfile(
        skills=["Python", "FastAPI"],
        preferred_roles=["Backend Engineer"],
        experience_level="mid",
        preferences="Remote only",
    )

    text = profile_embedding_text(profile)

    assert "Skills: Python, FastAPI" in text
    assert "Preferred roles: Backend Engineer" in text
    assert "Experience: mid" in text
    assert "Preferences: Remote only" in text


def test_empty_profile_returns_no_matches() -> None:
    """An empty profile does not query the database."""

    def fail(statement, params):
        raise AssertionError("database should not be queried")

    db = FakeSession(rows=[])
    db.execute = fail

    assert find_matching_jobs(db, JobSeekerProfile()) == []


def test_python_profile_ranks_python_job_above_react_job(monkeypatch) -> None:
    """A Python profile prefers a Python job over a React job."""
    db = FakeSession(
        rows=[
            job_row("Python Backend Engineer", ["Python", "FastAPI"], "mid", 0.05),
            job_row("React Frontend Engineer", ["React", "TypeScript"], "mid", 0.20),
        ]
    )
    monkeypatch.setattr(
        "app.services.job_matching.embed_text",
        lambda value: [0.1] * 384,
    )
    profile = JobSeekerProfile(
        skills=["Python", "FastAPI"],
        preferred_roles=["Python Backend Engineer"],
        experience_level="mid",
    )

    matches = find_matching_jobs(db, profile, similarity_threshold=0.30)

    assert len(matches) == 2
    assert matches[0].role == "Python Backend Engineer"
    assert matches[1].role == "React Frontend Engineer"
    assert matches[0].match_score > matches[1].match_score
    assert 0.0 <= matches[0].match_score <= 100.0
    assert 0.0 <= matches[1].match_score <= 100.0


def test_react_profile_ranks_react_job_above_python_job(monkeypatch) -> None:
    """A React profile prefers a React job over a Python job."""
    db = FakeSession(
        rows=[
            job_row("React Frontend Engineer", ["React", "TypeScript"], "mid", 0.05),
            job_row("Python Backend Engineer", ["Python", "FastAPI"], "mid", 0.20),
        ]
    )
    monkeypatch.setattr(
        "app.services.job_matching.embed_text",
        lambda value: [0.1] * 384,
    )
    profile = JobSeekerProfile(
        skills=["React", "TypeScript"],
        preferred_roles=["React Frontend Engineer"],
        experience_level="mid",
    )

    matches = find_matching_jobs(db, profile, similarity_threshold=0.30)

    assert len(matches) == 2
    assert matches[0].role == "React Frontend Engineer"
    assert matches[1].role == "Python Backend Engineer"
    assert matches[0].match_score > matches[1].match_score


def test_matching_uses_pgvector_cosine_query(monkeypatch) -> None:
    """Matching queries pgvector with cosine distance and a threshold."""
    db = FakeSession(rows=[])
    monkeypatch.setattr(
        "app.services.job_matching.embed_text",
        lambda value: [0.1] * 384,
    )

    find_matching_jobs(
        db,
        JobSeekerProfile(skills=["Python"]),
        similarity_threshold=0.40,
        limit=3,
        candidate_limit=25,
    )

    assert "<=>" in db.statements[0]
    assert "CAST(:embedding AS vector)" in db.statements[0]
    assert db.params["max_distance"] == pytest.approx(0.60)
    assert db.params["candidate_limit"] == 25


def test_matching_threshold_is_clamped(monkeypatch) -> None:
    """Thresholds outside zero to one are clamped safely."""
    db = FakeSession(rows=[])
    monkeypatch.setattr(
        "app.services.job_matching.embed_text",
        lambda value: [0.1] * 384,
    )

    find_matching_jobs(
        db,
        JobSeekerProfile(skills=["Python"]),
        similarity_threshold=5.0,
    )

    assert db.params["max_distance"] == pytest.approx(0.0)


def test_matching_limits_returned_rows(monkeypatch) -> None:
    """Only the requested number of ranked matches is returned."""
    db = FakeSession(
        rows=[
            job_row("Python Engineer", ["Python"], "mid", 0.05),
            job_row("React Engineer", ["React"], "mid", 0.10),
            job_row("Data Engineer", ["SQL"], "mid", 0.15),
        ]
    )
    monkeypatch.setattr(
        "app.services.job_matching.embed_text",
        lambda value: [0.1] * 384,
    )

    matches = find_matching_jobs(
        db,
        JobSeekerProfile(skills=["Python"], experience_level="mid"),
        limit=2,
    )

    assert len(matches) == 2
    assert matches[0].match_score >= matches[1].match_score
