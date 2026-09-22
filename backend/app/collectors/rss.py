import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx
import structlog

from app.collectors.base import RawPost, SourceAdapter
from app.collectors.errors import AdapterConfigError, RobotsDisallowedError
from app.collectors.http import PoliteHttpClient
from app.core.text import clean_text, html_to_text
from app.db.enums import SourceKind

log = structlog.get_logger()


class RssAdapter(SourceAdapter):
    """Generic RSS/Atom feeds. config: {"feeds": ["https://.../feed.xml", ...]}.

    Feed URLs are arbitrary, so robots.txt is checked before each fetch. One broken feed is
    logged and skipped; it does not stop the others.
    """

    kind = SourceKind.RSS

    def __init__(self, http: PoliteHttpClient, config: dict[str, Any] | None = None) -> None:
        self._http = http
        self._feeds: list[str] = (config or {}).get("feeds", [])
        if not self._feeds:
            raise AdapterConfigError("RSS source has no feeds: set config.feeds on the source")

    async def fetch(self, since: datetime | None = None) -> AsyncIterator[RawPost]:
        for url in self._feeds:
            try:
                response = await self._http.get(url, check_robots=True)
            except (httpx.HTTPError, RobotsDisallowedError) as exc:
                log.warning("rss_feed_skipped", feed=url, error=str(exc) or repr(exc))
                continue
            for entry in feedparser.parse(response.content).entries:
                post = _to_post(entry, feed_url=url)
                if post is None:
                    continue
                if since and post.posted_at and post.posted_at <= since:
                    continue
                yield post


def _to_post(entry: Any, *, feed_url: str) -> RawPost | None:
    link = entry.get("link")
    title = clean_text(entry.get("title", ""))
    if entry.get("content"):
        body_html = entry["content"][0].get("value", "")
    else:
        body_html = entry.get("summary", "")
    text = "\n\n".join(part for part in (title, html_to_text(body_html)) if part)
    if not text or not (link or entry.get("id")):
        return None
    external_id = entry.get("id") or hashlib.sha256((link or "").encode()).hexdigest()
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    return RawPost(
        external_id=external_id,
        url=link or feed_url,
        author_handle=entry.get("author"),
        raw_text=text,
        posted_at=datetime(*published[:6], tzinfo=UTC) if published else None,
        extra={"feed_url": feed_url},
    )
