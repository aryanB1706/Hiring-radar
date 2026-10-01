"""Tests for the Hacker News and RSS collectors."""

import httpx
import pytest

from app.collectors.base import CollectorError
from app.collectors.hacker_news import fetch_hacker_news
from app.collectors.rss import fetch_rss
from app.db.enums import SourceKind


class FakeResponse:
    """Minimal stand-in for an httpx.Response."""

    def __init__(self, json_data: dict | None = None, content: bytes = b"") -> None:
        self._json = json_data or {}
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._json


def test_fetch_hacker_news_normalizes(monkeypatch) -> None:
    """HN hits are converted to the common signal format."""

    def fake_get(url: str, **kwargs) -> FakeResponse:
        return FakeResponse(
            json_data={
                "hits": [
                    {
                        "objectID": "101",
                        "title": "Acme is hiring a Python Engineer",
                        "story_text": "<p>FastAPI and PostgreSQL</p>",
                        "url": "https://acme.example/jobs/101",
                        "author": "alice",
                        "created_at": "2026-11-01T10:00:00Z",
                    },
                    {
                        "objectID": "102",
                        "title": "Hiring backend developer",
                        "story_text": None,
                        "url": None,
                        "author": "bob",
                        "created_at": "2026-11-02T10:00:00Z",
                    },
                ]
            }
        )

    monkeypatch.setattr("app.collectors.hacker_news.httpx.get", fake_get)

    signals = fetch_hacker_news(limit=10)

    assert len(signals) == 2
    assert signals[0].title == "Acme is hiring a Python Engineer"
    assert signals[0].content == "FastAPI and PostgreSQL"
    assert signals[0].url == "https://acme.example/jobs/101"
    assert signals[0].source_kind == SourceKind.HN
    assert signals[0].source_name == "Hacker News"
    assert signals[0].author_handle == "alice"
    assert signals[0].posted_at is not None
    assert signals[1].url == "https://news.ycombinator.com/item?id=102"


def test_fetch_hacker_news_handles_network_error(monkeypatch) -> None:
    """Network failures become a CollectorError."""

    def fake_get(*args, **kwargs):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr("app.collectors.hacker_news.httpx.get", fake_get)

    with pytest.raises(CollectorError):
        fetch_hacker_news()


RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Python Jobs Feed</title>
    <item>
      <title>Python Intern</title>
      <link>https://example.com/jobs/1</link>
      <description><![CDATA[<p>FastAPI and PostgreSQL</p>]]></description>
      <guid>job-1</guid>
      <pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate>
      <author>alice@example.com</author>
    </item>
    <item>
      <title>Backend Engineer</title>
      <link>https://example.com/jobs/2</link>
      <description>Django role</description>
      <guid>job-2</guid>
    </item>
  </channel>
</rss>
"""


def test_fetch_rss_normalizes(monkeypatch) -> None:
    """RSS entries are converted to the common signal format."""

    def fake_get(url: str, **kwargs) -> FakeResponse:
        return FakeResponse(content=RSS_XML)

    monkeypatch.setattr("app.collectors.rss.httpx.get", fake_get)

    signals = fetch_rss(["https://example.com/feed"], limit_per_feed=10)

    assert len(signals) == 2
    assert signals[0].title == "Python Intern"
    assert signals[0].content == "FastAPI and PostgreSQL"
    assert signals[0].url == "https://example.com/jobs/1"
    assert signals[0].source_kind == SourceKind.RSS
    assert signals[0].source_name == "Python Jobs Feed"
    assert signals[0].external_id == "job-1"
    assert signals[0].posted_at is not None


def test_fetch_rss_handles_network_error(monkeypatch) -> None:
    """A network failure for every feed becomes a CollectorError."""

    def fake_get(*args, **kwargs):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr("app.collectors.rss.httpx.get", fake_get)

    with pytest.raises(CollectorError):
        fetch_rss(["https://example.com/feed"])


def test_fetch_rss_continues_when_one_feed_fails(monkeypatch) -> None:
    """One failing feed does not stop the remaining feeds."""
    calls = {"count": 0}

    def fake_get(url: str, **kwargs) -> FakeResponse:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("network down")
        return FakeResponse(content=RSS_XML)

    monkeypatch.setattr("app.collectors.rss.httpx.get", fake_get)

    signals = fetch_rss(["https://bad.example/feed", "https://good.example/feed"])

    assert len(signals) == 2
