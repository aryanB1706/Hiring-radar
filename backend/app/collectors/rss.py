"""RSS feed collector."""

from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx

from app.collectors.base import CollectedSignal, CollectorError, clean_html
from app.core.logging import get_logger
from app.db.enums import SourceKind

logger = get_logger("app.collectors.rss")


def fetch_rss(feed_urls: list[str], limit_per_feed: int = 20) -> list[CollectedSignal]:
    """Fetch entries from the configured RSS feeds."""
    if not feed_urls:
        raise CollectorError("No RSS feeds configured")

    signals: list[CollectedSignal] = []
    failures = 0

    for feed_url in feed_urls:
        try:
            response = httpx.get(
                feed_url,
                timeout=15,
                follow_redirects=True,
                headers={"User-Agent": "HiringRadar/0.1"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            failures += 1
            logger.warning("rss_fetch_failed", feed=feed_url, error=str(exc))
            continue

        feed = feedparser.parse(response.content)
        source_name = (feed.feed.get("title") or feed_url).strip()

        for entry in feed.entries[:limit_per_feed]:
            signal = _entry_to_signal(entry, source_name)
            if signal is not None:
                signals.append(signal)

    if failures == len(feed_urls):
        raise CollectorError("Could not fetch any RSS feed")

    return signals


def _entry_to_signal(entry: Any, source_name: str) -> CollectedSignal | None:
    """Convert one feedparser entry into the common signal format."""
    link = (entry.get("link") or entry.get("id") or "").strip()
    title = clean_html(entry.get("title"))
    content = clean_html(entry.get("summary") or entry.get("description")) or title
    if not link or not content:
        return None

    return CollectedSignal(
        external_id=(entry.get("id") or link).strip(),
        title=title or "RSS post",
        content=content,
        url=link,
        source_kind=SourceKind.RSS,
        source_name=source_name,
        author_handle=entry.get("author"),
        posted_at=_entry_datetime(entry),
    )


def _entry_datetime(entry: Any) -> datetime | None:
    """Convert feedparser's parsed date into a timezone-aware datetime."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=UTC)
