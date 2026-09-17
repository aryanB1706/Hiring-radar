import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog

from app.llm.errors import LLMTransientError

log = structlog.get_logger()


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 2  # retries after the first attempt
    base_delay: float = 1.0
    max_delay: float = 30.0
    max_retry_after: float = 60.0  # if the provider asks us to wait longer, give up instead


async def retry_transient[T](
    call: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], Awaitable[None]],
    rng: random.Random,
) -> T:
    """Retry only LLMTransientError; anything else (e.g. a 4xx) propagates immediately."""
    for attempt in range(policy.max_retries + 1):
        try:
            return await call()
        except LLMTransientError as exc:
            if attempt == policy.max_retries:
                raise
            if exc.retry_after is not None:
                if exc.retry_after > policy.max_retry_after:
                    raise
                delay = exc.retry_after
            else:
                ceiling = min(policy.max_delay, policy.base_delay * 2**attempt)
                delay = ceiling * (0.5 + rng.random() / 2)  # jitter: 50-100% of the ceiling
            log.warning("llm_retry", attempt=attempt + 1, delay_s=round(delay, 3), error=str(exc))
            await sleep(delay)
    raise AssertionError("unreachable")
