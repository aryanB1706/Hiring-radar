from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import Check, get_db_check, get_redis_check
from app.main import create_app


async def _up() -> None:
    return None


async def _down() -> None:
    raise ConnectionError("simulated outage")


def _client_with(db: Check, redis: Check) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_db_check] = lambda: db
    app.dependency_overrides[get_redis_check] = lambda: redis
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def healthy_client() -> AsyncIterator[AsyncClient]:
    async with _client_with(_up, _up) as client:
        yield client


async def test_health_ok(healthy_client: AsyncClient) -> None:
    response = await healthy_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "redis": "ok"}


async def test_health_returns_503_when_a_dependency_is_down() -> None:
    async with _client_with(_up, _down) as client:
        response = await client.get("/api/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "ok", "redis": "down"}


async def test_request_id_is_generated_and_echoed(healthy_client: AsyncClient) -> None:
    generated = await healthy_client.get("/api/health")
    assert generated.headers["X-Request-ID"]

    echoed = await healthy_client.get("/api/health", headers={"X-Request-ID": "abc123"})
    assert echoed.headers["X-Request-ID"] == "abc123"
