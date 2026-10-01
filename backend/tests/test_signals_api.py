"""Tests for signal storage and collection endpoints."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.collectors.base import CollectedSignal, CollectorError
from app.db.enums import SourceKind
from app.db.models import Post
from app.db.session import get_db
from app.services.signals import save_signals


def make_signal(**overrides) -> CollectedSignal:
    """Build a normalized signal for tests."""
    data = {
        "external_id": "hn-101",
        "title": "Acme is hiring a Python Engineer",
        "content": "FastAPI and PostgreSQL",
        "url": "https://acme.example/jobs/101",
        "source_kind": SourceKind.HN,
        "source_name": "Hacker News",
        "author_handle": "alice",
        "posted_at": None,
    }
    data.update(overrides)
    return CollectedSignal(**data)


def test_save_signals_deduplicates(db_session) -> None:
    """Saving the same signal twice creates one row."""
    signal = make_signal()

    assert save_signals(db_session, [signal]) == (1, 0)
    assert save_signals(db_session, [signal]) == (0, 1)
    count = db_session.scalar(select(func.count()).select_from(Post).where(Post.url == signal.url))
    assert count == 1


def test_save_signals_deduplicates_by_url(db_session) -> None:
    """A different post with the same URL is skipped."""
    first = make_signal()
    second = make_signal(
        external_id="hn-102",
        title="Different title",
        content="Different content",
    )

    assert save_signals(db_session, [first]) == (1, 0)
    assert save_signals(db_session, [second]) == (0, 1)


def test_save_signals_deduplicates_by_content_hash(db_session) -> None:
    """A different URL with identical content is skipped by the SHA256 hash."""
    first = make_signal()
    second = make_signal(
        external_id="hn-103",
        url="https://acme.example/jobs/other",
    )

    assert save_signals(db_session, [first]) == (1, 0)
    assert save_signals(db_session, [second]) == (0, 1)


def test_collect_hacker_news_endpoint(app, client: TestClient, db_session, monkeypatch) -> None:
    """The HN endpoint stores signals and skips duplicates on the next run."""
    app.dependency_overrides[get_db] = lambda: db_session
    monkeypatch.setattr(
        "app.api.collect.fetch_hacker_news",
        lambda limit: [make_signal()],
    )

    try:
        first = client.post("/api/collect/hacker-news")
        assert first.status_code == 200
        assert first.json() == {
            "source": "hacker-news",
            "fetched": 1,
            "created": 1,
            "skipped": 0,
        }

        second = client.post("/api/collect/hacker-news")
        assert second.json()["skipped"] == 1

        listed = client.get("/api/signals?limit=200")
        assert listed.status_code == 200
        body = listed.json()
        match = next(
            (item for item in body if item["url"] == "https://acme.example/jobs/101"),
            None,
        )
        assert match is not None
        assert match["source"] == "Hacker News"
        assert match["source_kind"] == "hn"
        assert match["content"] == "FastAPI and PostgreSQL"
    finally:
        app.dependency_overrides.clear()


def test_collect_rss_endpoint(app, client: TestClient, db_session, monkeypatch) -> None:
    """The RSS endpoint stores normalized RSS signals."""
    app.dependency_overrides[get_db] = lambda: db_session
    monkeypatch.setattr("app.api.collect.get_rss_feeds", lambda: ["https://example.com/feed"])
    monkeypatch.setattr(
        "app.api.collect.fetch_rss",
        lambda feeds, limit_per_feed: [
            make_signal(
                external_id="rss-1",
                source_kind=SourceKind.RSS,
                source_name="Python Jobs Feed",
                url="https://example.com/jobs/1",
            )
        ],
    )

    try:
        response = client.post("/api/collect/rss")
        assert response.status_code == 200
        assert response.json() == {
            "source": "rss",
            "fetched": 1,
            "created": 1,
            "skipped": 0,
        }
    finally:
        app.dependency_overrides.clear()


def test_collect_rss_requires_feeds(app, client: TestClient, monkeypatch) -> None:
    """The RSS endpoint returns 400 when no feeds are configured."""
    monkeypatch.setattr("app.api.collect.get_rss_feeds", lambda: [])

    response = client.post("/api/collect/rss")

    assert response.status_code == 400


def test_collect_hacker_news_returns_502_on_network_error(
    app, client: TestClient, monkeypatch
) -> None:
    """Collector network errors are returned as 502."""

    def fail(limit: int):
        raise CollectorError("Could not fetch Hacker News posts")

    monkeypatch.setattr("app.api.collect.fetch_hacker_news", fail)

    response = client.post("/api/collect/hacker-news")

    assert response.status_code == 502
