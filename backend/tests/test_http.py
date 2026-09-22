import httpx
import pytest

from app.collectors.errors import RobotsDisallowedError
from app.collectors.http import PoliteHttpClient
from tests.llm_helpers import FakeClock

UA = "TestBot/1.0 (+https://example.com/bot)"


def client_for(handler, clock: FakeClock, min_delay: float = 2.0) -> PoliteHttpClient:  # type: ignore[no-untyped-def]
    return PoliteHttpClient(
        UA,
        min_delay=min_delay,
        transport=httpx.MockTransport(handler),
        clock=clock.time,
        sleep=clock.sleep,
    )


async def test_requests_identify_the_app() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, text="ok")

    await client_for(handler, FakeClock()).get("https://a.example/x")
    assert seen == [UA]


async def test_same_host_requests_are_spaced_but_other_hosts_are_not() -> None:
    clock = FakeClock()
    http = client_for(lambda r: httpx.Response(200), clock, min_delay=2.0)

    await http.get("https://a.example/1")
    await http.get("https://a.example/2")  # too soon: must wait
    assert clock.sleeps == [pytest.approx(2.0)]

    await http.get("https://b.example/1")  # different host: no wait
    assert len(clock.sleeps) == 1


async def test_errors_raise() -> None:
    http = client_for(lambda r: httpx.Response(503), FakeClock())
    with pytest.raises(httpx.HTTPStatusError):
        await http.get("https://a.example/x")


def robots_site(robots: httpx.Response | None, hits: list[str]):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(request.url.path)
        if request.url.path == "/robots.txt":
            if robots is None:
                raise httpx.ConnectError("down")
            return robots
        return httpx.Response(200, text="content")

    return handler


async def test_robots_disallow_blocks_the_fetch() -> None:
    hits: list[str] = []
    robots = httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
    http = client_for(robots_site(robots, hits), FakeClock())

    with pytest.raises(RobotsDisallowedError):
        await http.get("https://a.example/private/feed.xml", check_robots=True)
    assert "/private/feed.xml" not in hits  # never requested

    assert (
        await http.get("https://a.example/public/feed.xml", check_robots=True)
    ).text == "content"


async def test_robots_is_fetched_once_per_host() -> None:
    hits: list[str] = []
    http = client_for(robots_site(httpx.Response(200, text=""), hits), FakeClock())
    await http.get("https://a.example/1", check_robots=True)
    await http.get("https://a.example/2", check_robots=True)
    assert hits.count("/robots.txt") == 1


async def test_missing_robots_means_allowed() -> None:
    http = client_for(robots_site(httpx.Response(404), []), FakeClock())
    assert await http.allowed_by_robots("https://a.example/anything")


@pytest.mark.parametrize("robots", [httpx.Response(500), None])
async def test_unavailable_robots_means_disallowed(robots: httpx.Response | None) -> None:
    http = client_for(robots_site(robots, []), FakeClock())
    assert not await http.allowed_by_robots("https://a.example/anything")


async def test_robots_check_is_opt_in() -> None:
    hits: list[str] = []
    http = client_for(
        robots_site(httpx.Response(200, text="User-agent: *\nDisallow: /"), hits), FakeClock()
    )
    await http.get("https://api.example/data")  # official API: no robots lookup
    assert hits == ["/data"]
