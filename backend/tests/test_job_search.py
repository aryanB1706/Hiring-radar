"""Tests for semantic embeddings and the pgvector job search tool."""

import uuid

from app.db.enums import LeadType
from app.db.models import Lead
from app.llm.classifier import JobClassification
from app.services.job_embeddings import (
    content_hash,
    embed_text,
    embedding_literal,
    index_job,
    job_embedding_text,
)
from app.tools.job_search import search_similar_jobs


class FakeVector:
    def __init__(self, values: list[float]) -> None:
        self.values = values

    def tolist(self) -> list[float]:
        return self.values


class FakeEmbeddingModel:
    def encode(self, value: str, normalize_embeddings: bool = True) -> FakeVector:
        return FakeVector([0.6, 0.8] + [0.0] * 382)


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

    def scalar(self):
        return self.rows


class FakeSession:
    def __init__(self, existing_hash=None, rows=None, error: Exception | None = None) -> None:
        self.existing_hash = existing_hash
        self.rows = rows or []
        self.error = error
        self.statements: list[str] = []
        self.params = {}
        self.closed = False
        self.committed = False

    def execute(self, statement, params):
        sql = str(statement)
        self.statements.append(sql)
        self.params = params
        if self.error:
            raise self.error
        if "SELECT content_hash" in sql:
            return FakeResult(self.existing_hash)
        return FakeResult(self.rows)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def test_embed_text_uses_sentence_transformer_model(monkeypatch) -> None:
    """The semantic embedder returns the model vector."""
    monkeypatch.setattr(
        "app.services.job_embeddings.get_embedding_model",
        lambda: FakeEmbeddingModel(),
    )

    vector = embed_text("Python FastAPI PostgreSQL")

    assert vector == [0.6, 0.8] + [0.0] * 382
    assert len(vector) == 384


def test_content_hash_is_stable() -> None:
    """The content hash changes only when the text changes."""
    assert content_hash("Python role") == content_hash("Python role")
    assert content_hash("Python role") != content_hash("React role")


def test_embedding_literal_is_pgvector_compatible() -> None:
    """The vector is formatted as a pgvector text literal."""
    literal = embedding_literal([0.5, -0.25])

    assert literal == "[0.50000000,-0.25000000]"


def test_job_embedding_text_includes_title_description_and_skills() -> None:
    """Job embeddings use the title, description, and skills."""
    text = job_embedding_text(
        JobClassification(
            is_hiring=True,
            company_name="Acme",
            job_title="Python Engineer",
            skills=["Python", "FastAPI"],
            job_type="full_time",
        ),
        description="Build backend services.",
    )

    assert "Title: Python Engineer" in text
    assert "Description: Build backend services." in text
    assert "Skills: Python, FastAPI" in text


def test_index_job_uses_pgvector_sql(monkeypatch) -> None:
    """Indexing uses a vector cast and stores a content hash."""
    db = FakeSession(existing_hash=None)
    lead = Lead(id=uuid.uuid4(), post_id=uuid.uuid4(), lead_type=LeadType.HIRING)
    result = JobClassification(
        is_hiring=True,
        company_name="Acme",
        job_title="Python Engineer",
        skills=["Python", "FastAPI"],
        location="Remote",
        job_type="full_time",
    )
    monkeypatch.setattr(
        "app.services.job_embeddings.embed_text",
        lambda content: [0.1] * 384,
    )

    changed = index_job(db, lead, result, description="Build APIs.")

    assert changed is True
    assert any("SELECT content_hash" in statement for statement in db.statements)
    assert any("job_embedding" in statement for statement in db.statements)
    assert any("CAST(:embedding AS vector)" in statement for statement in db.statements)
    assert db.params["lead_id"] == lead.id
    assert db.params["embedding"].startswith("[")
    assert len(db.params["content_hash"]) == 64
    assert db.committed is True


def test_index_job_skips_empty_content() -> None:
    """A job without searchable text is not indexed."""
    db = FakeSession()
    lead = Lead(id=uuid.uuid4(), post_id=uuid.uuid4(), lead_type=LeadType.HIRING)

    changed = index_job(db, lead, JobClassification(is_hiring=True))

    assert changed is False
    assert db.statements == []
    assert db.committed is False


def test_index_job_skips_unchanged_content(monkeypatch) -> None:
    """An unchanged job does not generate another embedding."""
    db = FakeSession(existing_hash="same-hash")
    lead = Lead(id=uuid.uuid4(), post_id=uuid.uuid4(), lead_type=LeadType.HIRING)
    result = JobClassification(is_hiring=True, job_title="Python Engineer")
    monkeypatch.setattr(
        "app.services.job_embeddings.content_hash",
        lambda content: "same-hash",
    )

    def fail_embedding(content):
        raise AssertionError("embed_text should not be called")

    monkeypatch.setattr("app.services.job_embeddings.embed_text", fail_embedding)

    changed = index_job(db, lead, result, description="Same description.")

    assert changed is False
    assert db.committed is False
    assert all("INSERT" not in statement for statement in db.statements)


def test_index_job_regenerates_changed_content(monkeypatch) -> None:
    """A changed job replaces its stored embedding."""
    db = FakeSession(existing_hash="old-hash")
    lead = Lead(id=uuid.uuid4(), post_id=uuid.uuid4(), lead_type=LeadType.HIRING)
    result = JobClassification(is_hiring=True, job_title="Python Engineer")
    monkeypatch.setattr(
        "app.services.job_embeddings.content_hash",
        lambda content: "new-hash",
    )
    monkeypatch.setattr(
        "app.services.job_embeddings.embed_text",
        lambda content: [0.2] * 384,
    )

    changed = index_job(db, lead, result, description="Updated description.")

    assert changed is True
    assert db.params["content_hash"] == "new-hash"
    assert db.committed is True


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
    monkeypatch.setattr(
        "app.tools.job_search.embed_text",
        lambda value: [0.1] * 384,
    )

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
    assert "<=>" in db.statements[0]
    assert "CAST(:embedding AS vector)" in db.statements[0]
    assert db.params["limit"] == 3
    assert db.closed is True


def test_search_similar_jobs_handles_database_error(monkeypatch) -> None:
    """Database failures return an empty result instead of crashing."""
    db = FakeSession(error=RuntimeError("database unavailable"))
    monkeypatch.setattr("app.tools.job_search.SessionLocal", lambda: db)
    monkeypatch.setattr(
        "app.tools.job_search.embed_text",
        lambda value: [0.1] * 384,
    )

    matches = search_similar_jobs.invoke({"query": "Python"})

    assert matches == []
    assert db.closed is True


def test_search_similar_jobs_skips_blank_query(monkeypatch) -> None:
    """A blank query does not open a database session."""

    def fail():
        raise AssertionError("SessionLocal should not be called")

    monkeypatch.setattr("app.tools.job_search.SessionLocal", fail)

    assert search_similar_jobs.invoke({"query": "   "}) == []
