import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import structlog

from app.collectors.base import RawPost, SourceAdapter
from app.collectors.http import PoliteHttpClient
from app.core.text import html_to_text
from app.db.enums import SourceKind

log = structlog.get_logger()

ALGOLIA = "https://hn.algolia.com/api/v1"

# Config name -> pattern for the monthly thread title posted by the "whoishiring" account.
THREAD_TITLES = {
    "hiring": re.compile(r"^Ask HN: Who is hiring\?", re.IGNORECASE),
    "seeking_work": re.compile(r"^Ask HN: Who wants to be hired\?", re.IGNORECASE),
    "freelance": re.compile(r"^Ask HN: Freelancer\? Seeking freelancer\?", re.IGNORECASE),
}


class HackerNewsAdapter(SourceAdapter):
    """Top-level comments of the latest 'Who is hiring?'-style threads (Algolia HN API).

    config: {"threads": ["hiring", "seeking_work", "freelance"]}  (default: ["hiring"])
    """

    kind = SourceKind.HN

    def __init__(self, http: PoliteHttpClient, config: dict[str, Any] | None = None) -> None:
        self._http = http
        self._threads: list[str] = (config or {}).get("threads", ["hiring"])
        unknown = set(self._threads) - THREAD_TITLES.keys()
        if unknown:
            raise ValueError(f"unknown HN thread kinds: {sorted(unknown)}")

    async def fetch(self, since: datetime | None = None) -> AsyncIterator[RawPost]:
        search = await self._http.get(
            f"{ALGOLIA}/search_by_date",
            params={"tags": "story,author_whoishiring", "hitsPerPage": 30},
        )
        hits: list[dict[str, Any]] = search.json()["hits"]
        for thread_kind in self._threads:
            hit = self._latest(hits, thread_kind)
            if hit is None:
                log.warning("hn_thread_not_found", thread=thread_kind)
                continue
            tree = (await self._http.get(f"{ALGOLIA}/items/{hit['objectID']}")).json()
            for comment in tree.get("children", []):  # top-level comments only
                post = self._to_post(comment, tree, thread_kind)
                if post is None:
                    continue
                if since and post.posted_at and post.posted_at <= since:
                    continue
                yield post

    @staticmethod
    def _latest(hits: list[dict[str, Any]], thread_kind: str) -> dict[str, Any] | None:
        pattern = THREAD_TITLES[thread_kind]
        matching = [h for h in hits if pattern.match(h.get("title") or "")]
        return max(matching, key=lambda h: h["created_at_i"], default=None)

    @staticmethod
    def _to_post(comment: dict[str, Any], thread: dict[str, Any], kind: str) -> RawPost | None:
        if not comment.get("text"):  # deleted or dead comments come back without text
            return None
        return RawPost(
            external_id=str(comment["id"]),
            url=f"https://news.ycombinator.com/item?id={comment['id']}",
            author_handle=comment.get("author"),
            raw_text=html_to_text(comment["text"]),
            posted_at=datetime.fromtimestamp(comment["created_at_i"], tz=UTC),
            extra={"thread_id": thread["id"], "thread_title": thread["title"], "thread": kind},
        )
