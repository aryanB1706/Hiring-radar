"""Tests for the Groq connectivity endpoint using a fake LLM."""

from fastapi import status
from fastapi.testclient import TestClient


class FakeMessage:
    """Minimal stand-in for a LangChain AIMessage."""

    content = "ok"


class FakeLLM:
    """Minimal stand-in for ChatGroq."""

    def invoke(self, prompt: str) -> FakeMessage:
        return FakeMessage()


def test_groq_test_success(monkeypatch, client: TestClient) -> None:
    """The endpoint returns the model reply when Groq is reachable."""
    monkeypatch.setattr("app.api.groq.get_llm", lambda: FakeLLM())

    response = client.get("/api/groq/test")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "ok"
    assert response.json()["reply"] == "ok"


def test_groq_test_missing_key(monkeypatch, client: TestClient) -> None:
    """The endpoint returns 503 when the API key is missing."""

    def raise_missing_key():
        raise ValueError("GROQ_API_KEY is not set")

    monkeypatch.setattr("app.api.groq.get_llm", raise_missing_key)

    response = client.get("/api/groq/test")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()["detail"] == "GROQ_API_KEY is not set"


def test_groq_test_provider_error(monkeypatch, client: TestClient) -> None:
    """The endpoint returns 503 when the Groq call fails."""

    def raise_provider_error():
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.api.groq.get_llm", raise_provider_error)

    response = client.get("/api/groq/test")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()["detail"] == "Groq connectivity check failed"
