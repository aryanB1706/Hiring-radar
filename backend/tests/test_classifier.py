"""Tests for Groq job classification."""

import uuid

import pytest

from app.db.enums import SourceKind
from app.db.models import Post, Source
from app.llm.classifier import ClassificationError, JobClassification, classify_signal


class FakeStructuredLLM:
    """Stand-in for a LangChain structured-output runnable."""

    def __init__(self, result) -> None:
        self.result = result

    def invoke(self, prompt: str):
        return self.result


class FakeLLM:
    """Stand-in for ChatGroq."""

    def __init__(self, result) -> None:
        self.result = result

    def with_structured_output(self, schema):
        assert schema is JobClassification
        return FakeStructuredLLM(self.result)


def make_post(
    title: str = "Acme is hiring a Python Engineer",
    content: str = "Acme is hiring. Apply at https://acme.example/jobs/1",
    url: str = "https://acme.example/jobs/1",
) -> Post:
    """Build an in-memory post for classification tests."""
    source = Source(kind=SourceKind.HN, name="Hacker News", enabled=True, config={})
    return Post(
        source=source,
        external_id=uuid.uuid4().hex,
        title=title,
        url=url,
        raw_text=content,
        content_hash=uuid.uuid4().hex,
    )


def test_classify_genuine_hiring(monkeypatch) -> None:
    """A real opening is classified with its extracted details."""
    expected = JobClassification(
        is_hiring=True,
        company_name="Acme",
        job_title="Python Engineer",
        skills=["Python", "FastAPI"],
        experience_level="Senior",
        job_type="full_time",
        location="Remote",
        application_url="https://acme.example/jobs/1",
        confidence=0.95,
    )
    monkeypatch.setattr("app.llm.classifier.get_llm", lambda: FakeLLM(expected))

    result = classify_signal(
        make_post(
            title="Acme is hiring a Senior Python Engineer",
            content=(
                "Acme is hiring a Senior Python Engineer. "
                "Skills: Python, FastAPI. Remote. "
                "Apply at https://acme.example/jobs/1"
            ),
        )
    )

    assert result.is_hiring is True
    assert result.company_name == "Acme"
    assert result.job_title == "Python Engineer"
    assert result.skills == ["Python", "FastAPI"]
    assert result.experience_level == "Senior"
    assert result.job_type == "full_time"
    assert result.location == "Remote"
    assert result.application_url == "https://acme.example/jobs/1"
    assert result.confidence == 0.95


def test_classify_rejects_tech_discussion(monkeypatch) -> None:
    """A technical discussion is not treated as a job."""
    expected = JobClassification(is_hiring=False, confidence=0.9)
    monkeypatch.setattr("app.llm.classifier.get_llm", lambda: FakeLLM(expected))

    result = classify_signal(
        make_post(
            title="Why Python is popular for data science",
            content="A discussion about Python libraries and performance.",
        )
    )

    assert result.is_hiring is False
    assert result.company_name is None
    assert result.job_title is None
    assert result.skills == []
    assert result.application_url is None


def test_classify_ambiguous_post(monkeypatch) -> None:
    """A possible future opening is not treated as a confirmed job."""
    expected = JobClassification(
        is_hiring=False,
        company_name=None,
        job_title=None,
        confidence=0.45,
    )
    monkeypatch.setattr("app.llm.classifier.get_llm", lambda: FakeLLM(expected))

    result = classify_signal(
        make_post(
            title="Thinking about hiring a backend developer",
            content="We may hire a backend developer next quarter. No role is open yet.",
        )
    )

    assert result.is_hiring is False
    assert result.job_title is None
    assert result.confidence == 0.45


def test_classification_normalizes_missing_fields(monkeypatch) -> None:
    """Blank text, missing skills, and percentage confidence are normalized."""
    raw = {
        "is_hiring": True,
        "company_name": "  ",
        "job_title": "Backend Intern",
        "skills": None,
        "experience_level": "",
        "job_type": "Full-time",
        "location": "  ",
        "application_url": "",
        "confidence": 87,
    }
    monkeypatch.setattr("app.llm.classifier.get_llm", lambda: FakeLLM(raw))

    result = classify_signal(make_post())

    assert result.company_name is None
    assert result.skills == []
    assert result.experience_level is None
    assert result.job_type == "full_time"
    assert result.location is None
    assert result.application_url is None
    assert result.confidence == 0.87


def test_classification_rejects_invalid_output(monkeypatch) -> None:
    """Invalid LLM output is wrapped in ClassificationError."""
    raw = {"is_hiring": True, "confidence": 150}
    monkeypatch.setattr("app.llm.classifier.get_llm", lambda: FakeLLM(raw))

    with pytest.raises(ClassificationError):
        classify_signal(make_post())


def test_classification_handles_llm_failure(monkeypatch) -> None:
    """Groq or LangChain failures are wrapped in ClassificationError."""

    class FailingLLM:
        def with_structured_output(self, schema):
            raise RuntimeError("Groq unavailable")

    monkeypatch.setattr("app.llm.classifier.get_llm", lambda: FailingLLM())

    with pytest.raises(ClassificationError):
        classify_signal(make_post())
