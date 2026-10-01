"""Hacker News collector using the public Algolia API."""

from datetime import datetime

import httpx

from app.collectors.base import CollectedSignal, CollectorError, clean_html
from app.core.logging import get_logger
from app.db.enums import SourceKind

HN_API_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_ITEM_URL = "https://news.ycombinator.com/item?id={}"
logger = get_logger("app.collectors.hacker_news")


def fetch_hacker_news(limit: int = 30) -> list[CollectedSignal]:
    """Fetch recent Hacker News stories mentioning hiring."""
    params = {"query": "hiring", "tags": "story", "hitsPerPage": limit}

    try:
        response = httpx.get(
            HN_API_URL,
            params=params,
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "HiringRadar/0.1"},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("hacker_news_fetch_failed", error=str(exc))
        raise CollectorError("Could not fetch Hacker News posts") from exc

    signals: list[CollectedSignal] = []
    for hit in response.json().get("hits", []):
        object_id = str(hit.get("objectID", "")).strip()
        title = clean_html(hit.get("title"))
        content = clean_html(hit.get("story_text") or hit.get("comment_text")) or title
        if not object_id or not content:
            continue
        if "hiring" not in f"{title} {content}".lower():
            continue

        signals.append(
            CollectedSignal(
                external_id=object_id,
                title=title or "Hacker News post",
                content=content,
                url=(hit.get("url") or HN_ITEM_URL.format(object_id)).strip(),
                source_kind=SourceKind.HN,
                source_name="Hacker News",
                author_handle=hit.get("author"),
                posted_at=_parse_datetime(hit.get("created_at")),
            )
        )

    return signals


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse the ISO timestamp returned by the HN API."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
