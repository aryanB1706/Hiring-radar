import asyncio
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import structlog

from app.collectors.errors import RobotsDisallowedError

log = structlog.get_logger()


class PoliteHttpClient:
    """Shared httpx client: identifies us, has timeouts, waits between requests to the same host,
    and can check robots.txt before fetching a generic URL."""

    def __init__(
        self,
        user_agent: str,
        *,
        timeout: float = 20.0,
        min_delay: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.user_agent = user_agent
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._min_delay = min_delay
        self._clock = clock
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._robots: dict[str, RobotFileParser | None] = {}  # None = everything disallowed

    async def get(
        self, url: str, *, check_robots: bool = False, **kwargs: object
    ) -> httpx.Response:
        """GET with the per-host delay. Pass check_robots=True for any generic (non-API) URL."""
        if check_robots and not await self.allowed_by_robots(url):
            raise RobotsDisallowedError(f"robots.txt disallows {url} for {self.user_agent!r}")
        response = await self._throttled_get(url, **kwargs)
        response.raise_for_status()
        return response

    async def allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = await self._load_robots(origin)
        parser = self._robots[origin]
        return parser is not None and parser.can_fetch(self.user_agent, url)

    async def _load_robots(self, origin: str) -> RobotFileParser | None:
        """RFC 9309: 2xx -> parse; 4xx -> no rules (allowed); 5xx or unreachable -> disallowed."""
        try:
            response = await self._throttled_get(f"{origin}/robots.txt")
        except httpx.HTTPError as exc:
            log.warning("robots_unreachable", origin=origin, error=repr(exc))
            return None
        parser = RobotFileParser()
        if response.is_success:
            parser.parse(response.text.splitlines())
            return parser
        if response.status_code < 500:
            parser.parse([])
            return parser
        log.warning("robots_server_error", origin=origin, status=response.status_code)
        return None

    async def _throttled_get(self, url: str, **kwargs: object) -> httpx.Response:
        host = urlsplit(url).netloc
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:  # one request at a time per host, spaced by min_delay
            last = self._last_request.get(host)
            if last is not None:
                wait = self._min_delay - (self._clock() - last)
                if wait > 0:
                    await self._sleep(wait)
            try:
                return await self._client.get(url, **kwargs)  # type: ignore[arg-type]
            finally:
                self._last_request[host] = self._clock()

    async def aclose(self) -> None:
        await self._client.aclose()
