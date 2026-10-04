"""Tests for the pgvector job search tool and embeddings."""

import math
import uuid

from app.db.enums import LeadType
from app.db.models import Lead
from app.llm.classifier import JobClassification
from app.services.job_embeddings import embed_text, embedding_literal, index_job
from app.tools.job_search import search_similar_jobs


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
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self.rows = rows or []
        self.error = error
        self.statement = ""
        self.params = {}
        self.closed = False
        self.committed = False

    def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        if self.error:
            raise self.error
        return FakeResult(self.rows)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def test_embed_text_is_deterministic_and_normalized() -> None:
    """The same text always produces the same normalized vector."""
    first = embed_text("Python FastAPI PostgreSQL")
    second = embed_text("Python FastAPI PostgreSQL")

    assert first == second
    assert len(first) == 384
    assert math.isclose(sum(item * item for item in first), 1.0, rel_tol=1e-6)


def test_embedding_literal_is_pgvector_compatible() -> None:
    """The vector is formatted as a pgvector text literal."""
    literal = embedding_literal([0.5, -0.25])

    assert literal == "[0.50000000,-0.25000000]"


def test_index_job_uses_pgvector_sql() -> None:
    """Indexing uses a vector cast and upserts one embedding per lead."""
    db = FakeSession()
    lead = Lead(id=uuid.uuid4(), post_id=uuid.uuid4(), lead_type=LeadType.HIRING)
    result = JobClassification(
        is_hiring=True,
        company_name="Acme",
        job_title="Python Engineer",
        skills=["Python", "FastAPI"],
        location="Remote",
        job_type="full_time",
    )

    index_job(db, lead, result)

    assert "job_embedding" in db.statement
    assert "CAST(:embedding AS vector)" in db.statement
    assert db.params["lead_id"] == lead.id
    assert db.params["embedding"].startswith("[")
    assert db.committed is True


def test_index_job_skips_empty_content() -> None:
    """A job without searchable text is not indexed."""
    db = FakeSession()
    lead = Lead(id=uuid.uuid4(), post_id=uuid.uuid4(), lead_type=LeadType.HIRING)

    index_job(db, lead, JobClassification(is_hiring=True))

    assert db.statement == ""
    assert db.committed is False


def test_search_similar_jobs_returns_matches(monkeypatch) -> None:
    """The tool queries pgvector and returns readable job matches."""
    lead_id = uuid.uuid4()
    db = FakeSession(
        rows=[
            {
                "lead_id": lead_id,
                "company_name": "Acme",
                "role_title": "Python Engineer",
                "skills": ["Python"],
                "location": "Remote",
                "application_url": "https://acme.example/jobs/1",
                "distance": 0.123456,
            }
        ]
    )
    monkeypatch.setattr("app.tools.job_search.SessionLocal", lambda: db)

    matches = search_similar_jobs.invoke({"query": "Python FastAPI", "limit": 3})

    assert matches == [
        {
            "lead_id": str(lead_id),
            "company": "Acme",
            "role": "Python Engineer",
            "skills": ["Python"],
            "location": "Remote",
            "application_url": "https://acme.example/jobs/1",
            "distance": 0.1235,
        }
    ]
    assert "<=>" in db.statement
    assert "CAST(:embedding AS vector)" in db.statement
    assert db.params["limit"] == 3
    assert db.closed is True


def test_search_similar_jobs_handles_database_error(monkeypatch) -> None:
    """Database failures return an empty result instead of crashing."""
    db = FakeSession(error=RuntimeError("database unavailable"))
    monkeypatch.setattr("app.tools.job_search.SessionLocal", lambda: db)

    matches = search_similar_jobs.invoke({"query": "Python"})

    assert matches == []
    assert db.closed is True


def test_search_similar_jobs_skips_blank_query(monkeypatch) -> None:
    """A blank query does not open a database session."""

    def fail():
        raise AssertionError("SessionLocal should not be called")

    monkeypatch.setattr("app.tools.job_search.SessionLocal", fail)

    assert search_similar_jobs.invoke({"query": "   "}) == []
