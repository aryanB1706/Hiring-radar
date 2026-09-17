import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger()

# Sliding window in a sorted set. Returns 0 if a slot was taken, else seconds until one frees up.
_SCRIPT = """
local key, now, window, limit, member = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]),
    tonumber(ARGV[3]), ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
if redis.call('ZCARD', key) < limit then
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, math.ceil(window * 1000))
    return '0'
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
return tostring(tonumber(oldest[2]) + window - now)
"""


class RedisRateLimiter:
    """At most `limit` requests per `window` seconds, shared by every worker using the same key."""

    def __init__(
        self,
        redis: Redis,
        *,
        limit: int,
        key: str = "llm:rate",
        window: float = 60.0,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._script = redis.register_script(_SCRIPT)
        self._limit = limit
        self._key = key
        self._window = window
        self._clock = clock
        self._sleep = sleep

    async def acquire(self) -> None:
        while True:
            try:
                wait = float(
                    await self._script(
                        keys=[self._key],
                        args=[self._clock(), self._window, self._limit, uuid.uuid4().hex],
                    )
                )
            except RedisError as exc:
                log.warning("llm_rate_limiter_unavailable", error=repr(exc))
                return  # fail open: a Redis blip should not block every LLM call
            if wait <= 0:
                return
            await self._sleep(wait)
