import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.collectors.disabled import ADR, InstagramAdapter, LinkedInAdapter
from app.collectors.errors import AdapterConfigError, DisabledSourceError
from app.collectors.hn import HackerNewsAdapter
from app.collectors.http import PoliteHttpClient
from app.collectors.reddit import RedditAdapter
from app.collectors.registry import build_adapter
from app.collectors.rss import RssAdapter
from app.core.config import Settings
from app.db.enums import SourceKind
from app.db.models import Source

FIXTURES = Path(__file__).parent / "fixtures"


def http_with(handler) -> PoliteHttpClient:  # type: ignore[no-untyped-def]
    return PoliteHttpClient("TestBot/1.0", min_delay=0, transport=httpx.MockTransport(handler))


# --- Hacker News ------------------------------------------------------------------------------


def hn_handler(requested: list[str]):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        name = "search.json" if request.url.path.endswith("search_by_date") else "item.json"
        return httpx.Response(200, json=json.loads((FIXTURES / "hn" / name).read_text()))

    return handler


async def collect(adapter, since=None):  # type: ignore[no-untyped-def]
    return [post async for post in adapter.fetch(since)]


async def test_hn_yields_top_level_comments_as_clean_posts() -> None:
    requested: list[str] = []
    posts = await collect(HackerNewsAdapter(http_with(hn_handler(requested))))

    assert "/api/v1/items/49922569" in requested  # the latest "Who is hiring?" thread
    assert {p.external_id for p in posts} == {"49922609", "49922615", "49922621", "49922584"}
    first = next(p for p in posts if p.external_id == "49922609")
    assert first.url == "https://news.ycombinator.com/item?id=49922609"
    assert first.author_handle and first.posted_at and first.posted_at.tzinfo is not None
    assert first.extra["thread_title"].startswith("Ask HN: Who is hiring?")
    assert "R&D" in first.raw_text
    assert all("<" not in p.raw_text and "&amp;" not in p.raw_text for p in posts)


async def test_hn_skips_deleted_comments_and_nested_replies() -> None:
    posts = await collect(HackerNewsAdapter(http_with(hn_handler([]))))
    ids = {p.external_id for p in posts}
    assert "1" not in ids  # deleted comment, no text
    item = json.loads((FIXTURES / "hn" / "item.json").read_text())
    nested = {str(c["id"]) for top in item["children"] for c in top["children"]}
    assert nested and not (nested & ids)


async def test_hn_since_filters_older_comments() -> None:
    all_posts = await collect(HackerNewsAdapter(http_with(hn_handler([]))))
    cutoff = sorted(p.posted_at for p in all_posts if p.posted_at)[1]
    newer = await collect(HackerNewsAdapter(http_with(hn_handler([]))), since=cutoff)
    assert newer and all(p.posted_at and p.posted_at > cutoff for p in newer)
    assert len(newer) < len(all_posts)


async def test_hn_other_thread_kinds_are_configurable() -> None:
    requested: list[str] = []
    adapter = HackerNewsAdapter(
        http_with(hn_handler(requested)), {"threads": ["seeking_work", "freelance"]}
    )
    await collect(adapter)
    assert "/api/v1/items/49922568" in requested  # "Who wants to be hired?" (October)
    assert not any(p.endswith("49922569") for p in requested)
    # No "Freelancer?" thread in the fixture: that thread is skipped, not an error.
    assert sum(p.startswith("/api/v1/items/") for p in requested) == 1


def test_hn_rejects_unknown_thread_kind() -> None:
    with pytest.raises(ValueError):
        HackerNewsAdapter(http_with(lambda r: httpx.Response(200)), {"threads": ["nope"]})


# --- Reddit -----------------------------------------------------------------------------------


class FakeReddit:
    """Stands in for praw.Reddit, serving the hand-written fixture."""

    def __init__(self) -> None:
        data = json.loads((FIXTURES / "reddit" / "forhire_new.json").read_text())
        self.limits: list[int] = []
        self._data = {k: v for k, v in data.items() if k != "note"}

    def subreddit(self, name: str) -> SimpleNamespace:
        def new(limit: int) -> list[SimpleNamespace]:
            self.limits.append(limit)
            return [SimpleNamespace(**item) for item in self._data[name]]

        return SimpleNamespace(new=new)


async def test_reddit_yields_title_plus_body() -> None:
    fake = FakeReddit()
    adapter = RedditAdapter(
        lambda: fake, {"subreddits": ["forhire", "developersIndia"], "limit": 25}
    )
    posts = await collect(adapter)

    assert [p.external_id for p in posts] == ["1abc01", "1abc02", "1abc03"]
    assert fake.limits == [25, 25]
    hiring = posts[0]
    assert hiring.raw_text.startswith("[HIRING] Python/FastAPI backend developer")
    assert "DM me with your portfolio." in hiring.raw_text
    assert hiring.url.startswith("https://www.reddit.com/r/forhire/comments/1abc01/")
    assert hiring.author_handle == "startup_founder"
    assert hiring.extra["subreddit"] == "forhire"
    assert hiring.posted_at == datetime.fromtimestamp(1792000000, tz=UTC)


async def test_reddit_handles_deleted_author_and_empty_body() -> None:
    posts = await collect(RedditAdapter(lambda: FakeReddit(), {"subreddits": ["forhire"]}))
    deleted = posts[1]
    assert deleted.author_handle is None
    assert deleted.raw_text == "[FOR HIRE] Django developer available"


async def test_reddit_since_filters_older_submissions() -> None:
    adapter = RedditAdapter(lambda: FakeReddit(), {"subreddits": ["forhire"]})
    posts = await collect(adapter, since=datetime.fromtimestamp(1792000000, tz=UTC))
    assert [p.external_id for p in posts] == ["1abc02"]


def test_reddit_needs_credentials_and_subreddits() -> None:
    with pytest.raises(AdapterConfigError, match="credentials"):
        RedditAdapter(None, {"subreddits": ["forhire"]})
    with pytest.raises(AdapterConfigError, match="subreddits"):
        RedditAdapter(lambda: FakeReddit(), {})


# --- RSS / Atom -------------------------------------------------------------------------------

FEEDS = {
    "https://jobs.example.com/feed.xml": ("jobs.xml", 200),
    "https://gigs.example.com/atom.xml": ("atom.xml", 200),
}


def feed_handler(robots: dict[str, str] | None = None, broken: set[str] | None = None):  # type: ignore[no-untyped-def]
    robots = robots or {}
    broken = broken or set()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.path == "/robots.txt":
            body = robots.get(request.url.host)
            return httpx.Response(200, text=body) if body is not None else httpx.Response(404)
        if url in broken:
            return httpx.Response(500)
        return httpx.Response(200, content=(FIXTURES / "rss" / FEEDS[url][0]).read_bytes())

    return handler


async def test_rss_parses_rss_and_atom_feeds() -> None:
    adapter = RssAdapter(http_with(feed_handler()), {"feeds": list(FEEDS)})
    posts = {p.external_id: p for p in await collect(adapter)}

    assert set(posts) == {
        "job-1001",
        "job-1002",
        "tag:gigs.example.com,2026:gig-7",
    }  # empty item dropped
    job = posts["job-1001"]
    assert job.url == "https://jobs.example.com/python-engineer"
    assert job.raw_text == (
        "Senior Python Engineer (Remote)\n\n"
        "Acme is hiring a Senior Python Engineer.\n\nApply: here (https://acme.example/apply)"
    )
    assert job.posted_at == datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
    gig = posts["tag:gigs.example.com,2026:gig-7"]
    assert gig.author_handle == "Dana"
    assert "Budget $500, 1 week." in gig.raw_text


async def test_rss_since_filters_older_entries() -> None:
    adapter = RssAdapter(http_with(feed_handler()), {"feeds": list(FEEDS)})
    posts = await collect(adapter, since=datetime(2026, 10, 22, tzinfo=UTC))
    assert {p.external_id for p in posts} == {"job-1002", "tag:gigs.example.com,2026:gig-7"}


async def test_rss_respects_robots_and_survives_a_broken_feed() -> None:
    handler = feed_handler(
        robots={"jobs.example.com": "User-agent: *\nDisallow: /"},  # jobs feed is off limits
    )
    adapter = RssAdapter(http_with(handler), {"feeds": list(FEEDS)})
    assert {p.external_id for p in await collect(adapter)} == {"tag:gigs.example.com,2026:gig-7"}

    broken = feed_handler(broken={"https://jobs.example.com/feed.xml"})
    adapter = RssAdapter(http_with(broken), {"feeds": list(FEEDS)})
    assert {p.external_id for p in await collect(adapter)} == {"tag:gigs.example.com,2026:gig-7"}


def test_rss_needs_feeds() -> None:
    with pytest.raises(AdapterConfigError, match="no feeds"):
        RssAdapter(http_with(feed_handler()), {})


# --- disabled adapters ------------------------------------------------------------------------


@pytest.mark.parametrize("adapter_cls", [LinkedInAdapter, InstagramAdapter])
async def test_disabled_adapters_raise_and_point_to_the_adr(adapter_cls: type) -> None:
    adapter = adapter_cls()
    assert adapter.enabled is False
    with pytest.raises(DisabledSourceError, match="platform terms") as info:
        await collect(adapter)
    assert ADR in str(info.value)


# --- registry ---------------------------------------------------------------------------------


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def source(kind: SourceKind, config: dict | None = None) -> Source:
    return Source(kind=kind, name=f"{kind.value}-test", config=config or {}, enabled=True)


def test_registry_builds_each_pollable_adapter() -> None:
    http = http_with(lambda r: httpx.Response(200))
    assert isinstance(build_adapter(source(SourceKind.HN), settings(), http), HackerNewsAdapter)
    assert isinstance(
        build_adapter(source(SourceKind.RSS, {"feeds": ["https://x.example/f"]}), settings(), http),
        RssAdapter,
    )
    with_creds = settings(reddit_client_id="id", reddit_client_secret="secret")
    assert isinstance(build_adapter(source(SourceKind.REDDIT), with_creds, http), RedditAdapter)


def test_registry_reddit_without_credentials_is_a_clear_error() -> None:
    http = http_with(lambda r: httpx.Response(200))
    with pytest.raises(AdapterConfigError, match="REDDIT_CLIENT_ID"):
        build_adapter(source(SourceKind.REDDIT), settings(), http)


def test_registry_reddit_uses_configured_subreddits() -> None:
    assert settings(subreddits=" forhire, r/hiring ,").subreddit_list == ["forhire", "hiring"]


def test_registry_never_gives_a_working_linkedin_adapter() -> None:
    adapter = build_adapter(
        source(SourceKind.LINKEDIN_USER_CAPTURE),
        settings(),
        http_with(lambda r: httpx.Response(200)),
    )
    assert isinstance(adapter, LinkedInAdapter) and adapter.enabled is False


@pytest.mark.parametrize(
    "kind", [SourceKind.MANUAL_PASTE, SourceKind.CSV_IMPORT, SourceKind.GITHUB]
)
def test_registry_has_nothing_to_poll_for_capture_kinds(kind: SourceKind) -> None:
    with pytest.raises(AdapterConfigError):
        build_adapter(source(kind), settings(), http_with(lambda r: httpx.Response(200)))
