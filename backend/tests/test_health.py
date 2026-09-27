"""Tests for the /api/health endpoint."""

from fastapi import status
from fastapi.testclient import TestClient

from app.api.health import verify_db_connection


def test_health_check_success(app, client: TestClient) -> None:
    """Health check returns 200 and connected status when database ping succeeds."""
    app.dependency_overrides[verify_db_connection] = lambda: True

    response = client.get("/api/health")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok", "db": "connected"}
    assert "X-Request-ID" in response.headers


def test_health_check_503_when_db_down(app, client: TestClient) -> None:
    """Health check returns 503 and disconnected status when database ping fails."""
    app.dependency_overrides[verify_db_connection] = lambda: False

    response = client.get("/api/health")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {"status": "unhealthy", "db": "disconnected"}
    assert "X-Request-ID" in response.headers
