import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

from app.collectors.base import RawPost, SourceAdapter
from app.collectors.errors import AdapterConfigError
from app.core.text import clean_text
from app.db.enums import SourceKind

log = structlog.get_logger()


class RedditLike(Protocol):
    """The slice of praw.Reddit we use; tests pass a fake."""

    def subreddit(self, name: str) -> Any: ...


class RedditAdapter(SourceAdapter):
    """New submissions (title + body) from subreddits via the official API (PRAW, read-only).

    config: {"subreddits": [...], "limit": 100}. PRAW is blocking, so each subreddit is read in a
    worker thread. PRAW handles Reddit's own rate limits.
    """

    kind = SourceKind.REDDIT

    def __init__(
        self,
        client_factory: Callable[[], RedditLike] | None,
        config: dict[str, Any],
    ) -> None:
        if client_factory is None:
            raise AdapterConfigError(
                "Reddit credentials missing: set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET"
            )
        self._client_factory = client_factory
        self._subreddits: list[str] = config.get("subreddits", [])
        self._limit: int = config.get("limit", 100)
        if not self._subreddits:
            raise AdapterConfigError("Reddit source has no subreddits configured")

    async def fetch(self, since: datetime | None = None) -> AsyncIterator[RawPost]:
        reddit = await asyncio.to_thread(self._client_factory)
        for name in self._subreddits:
            submissions = await asyncio.to_thread(self._read, reddit, name)
            for submission in submissions:
                post = _to_post(submission)
                if since and post.posted_at and post.posted_at <= since:
                    continue
                yield post

    def _read(self, reddit: RedditLike, name: str) -> list[Any]:
        return list(reddit.subreddit(name).new(limit=self._limit))


def _to_post(submission: Any) -> RawPost:
    body = clean_text(submission.selftext or "")
    title = clean_text(submission.title)
    author = submission.author  # None when the account was deleted
    return RawPost(
        external_id=submission.id,
        url=f"https://www.reddit.com{submission.permalink}",
        author_handle=None if author is None else str(author),
        raw_text="\n\n".join(part for part in (title, body) if part),
        posted_at=datetime.fromtimestamp(submission.created_utc, tz=UTC),
        extra={
            "subreddit": str(submission.subreddit),
            "flair": getattr(submission, "link_flair_text", None),
        },
    )
