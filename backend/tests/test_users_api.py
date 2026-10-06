"""Tests for job seeker profile API endpoints."""

import uuid

from fastapi.testclient import TestClient

from app.db.session import get_db


def test_create_get_and_update_user(app, client: TestClient, db_session) -> None:
    """A user profile can be created, fetched, and partially updated."""
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        created = client.post(
            "/api/users",
            json={
                "name": "  Alice  ",
                "skills": ["Python", " python ", "FastAPI", ""],
                "preferred_roles": ["Backend Engineer"],
                "experience_level": "  Mid  ",
                "preferred_job_type": "full-time",
            },
        )
        assert created.status_code == 201
        body = created.json()
        user_id = body["id"]
        assert body["name"] == "Alice"
        assert body["skills"] == ["Python", "FastAPI"]
        assert body["preferred_roles"] == ["Backend Engineer"]
        assert body["experience_level"] == "Mid"
        assert body["preferred_job_type"] == "full_time"
        assert body["created_at"]

        fetched = client.get(f"/api/users/{user_id}")
        assert fetched.status_code == 200
        assert fetched.json() == body

        updated = client.put(
            f"/api/users/{user_id}",
            json={"skills": ["Python", "Django"], "preferred_job_type": "contract"},
        )
        assert updated.status_code == 200
        updated_body = updated.json()
        assert updated_body["name"] == "Alice"
        assert updated_body["skills"] == ["Python", "Django"]
        assert updated_body["preferred_roles"] == ["Backend Engineer"]
        assert updated_body["preferred_job_type"] == "contract"

        fetched_again = client.get(f"/api/users/{user_id}")
        assert fetched_again.json() == updated_body
    finally:
        app.dependency_overrides.clear()


def test_create_user_validation(app, client: TestClient, db_session) -> None:
    """Invalid user payloads are rejected by Pydantic."""
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        blank_name = client.post("/api/users", json={"name": "   "})
        assert blank_name.status_code == 422

        invalid_job_type = client.post(
            "/api/users",
            json={"name": "Alice", "preferred_job_type": "part_time"},
        )
        assert invalid_job_type.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_update_user_validation(app, client: TestClient, db_session) -> None:
    """PUT rejects null names and invalid list fields."""
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        created = client.post("/api/users", json={"name": "Alice"})
        user_id = created.json()["id"]

        null_name = client.put(f"/api/users/{user_id}", json={"name": None})
        assert null_name.status_code == 422

        null_skills = client.put(f"/api/users/{user_id}", json={"skills": None})
        assert null_skills.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_user_endpoints_return_404(app, client: TestClient, db_session) -> None:
    """Unknown user ids return 404."""
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        user_id = uuid.uuid4()
        assert client.get(f"/api/users/{user_id}").status_code == 404
        assert client.put(f"/api/users/{user_id}", json={"name": "Alice"}).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_swagger_docs_include_user_and_job_endpoints(client: TestClient) -> None:
    """Swagger UI loads and the OpenAPI schema contains every new endpoint."""
    docs = client.get("/docs")
    assert docs.status_code == 200

    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/users" in paths
    assert "/api/users/{user_id}" in paths
    assert "/api/jobs" in paths
    assert "/api/jobs/{job_id}" in paths
    assert "/api/jobs/recommended/{user_id}" in paths
