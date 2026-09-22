from praw import Reddit

from app.collectors.base import SourceAdapter
from app.collectors.disabled import LinkedInAdapter
from app.collectors.errors import AdapterConfigError
from app.collectors.hn import HackerNewsAdapter
from app.collectors.http import PoliteHttpClient
from app.collectors.reddit import RedditAdapter, RedditLike
from app.collectors.rss import RssAdapter
from app.core.config import Settings
from app.db.enums import SourceKind
from app.db.models import Source

POLLABLE_KINDS = {SourceKind.HN, SourceKind.REDDIT, SourceKind.RSS}


def _reddit_factory(settings: Settings):  # type: ignore[no-untyped-def]
    if not (settings.reddit_client_id and settings.reddit_client_secret):
        return None

    def make() -> RedditLike:
        reddit = Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret.get_secret_value(),
            user_agent=settings.reddit_user_agent,
        )
        reddit.read_only = True  # app-only auth: we never log in as a user
        return reddit

    return make


def build_adapter(source: Source, settings: Settings, http: PoliteHttpClient) -> SourceAdapter:
    match source.kind:
        case SourceKind.HN:
            return HackerNewsAdapter(http, source.config)
        case SourceKind.REDDIT:
            config = {"subreddits": settings.subreddit_list} | source.config
            return RedditAdapter(_reddit_factory(settings), config)
        case SourceKind.RSS:
            return RssAdapter(http, source.config)
        case SourceKind.LINKEDIN_USER_CAPTURE:
            return LinkedInAdapter()  # disabled by policy: fetch() raises
        case _:
            raise AdapterConfigError(
                f"source kind {source.kind.value!r} is fed by user capture, it has nothing to poll"
            )
