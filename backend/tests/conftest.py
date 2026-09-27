"""Pytest fixtures and configuration."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app():
    """Create a fresh app instance for testing."""
    return create_app()


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    """TestClient fixture with dependencies clean."""
    with TestClient(app) as test_client:
        yield test_client
