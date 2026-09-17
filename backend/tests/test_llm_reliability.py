import asyncio
import random
from decimal import Decimal

import pytest
import structlog
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import LLMCallLog
from app.llm import (
    Budget,
    BudgetExceeded,
    FakeLLMClient,
    Message,
    ModelTier,
    ToolCall,
    ToolSpec,
)
from app.llm.cache import ResponseCache, cache_key
from app.llm.call_log import DbCallLogger
from app.llm.errors import LLMPermanentError, LLMRateLimitError, LLMTransientError
from app.llm.pricing import ModelPrice
from app.llm.rate_limit import RedisRateLimiter
from app.llm.reliable import ReliableLLMClient
from app.llm.retry import RetryPolicy
from tests.llm_helpers import FakeClock


class Job(BaseModel):
    title: str


def build(
    inner: FakeLLMClient,
    clock: FakeClock,
    *,
    max_retries: int = 2,
    timeout: float = 5.0,
    **kwargs: object,
) -> ReliableLLMClient:
    return ReliableLLMClient(
        inner,
        retry=RetryPolicy(max_retries=max_retries),
        timeout_seconds=timeout,
        sleep=clock.sleep,
        rng=random.Random(0),
        **kwargs,  # type: ignore[arg-type]
    )


# --- retry / backoff --------------------------------------------------------------------------


async def test_429_is_retried_with_exponential_backoff_and_jitter() -> None:
    clock = FakeClock()
    inner = FakeLLMClient([LLMRateLimitError("429"), LLMRateLimitError("429"), "ok"])
    result = await build(inner, clock).generate_text("hi", purpose="t")

    assert result.text == "ok"
    assert len(inner.calls) == 3
    first, second = clock.sleeps
    assert 0.5 <= first <= 1.0  # base_delay * 2**0, jittered to 50-100%
    assert 1.0 <= second <= 2.0  # base_delay * 2**1


async def test_retry_after_is_honored() -> None:
    clock = FakeClock()
    inner = FakeLLMClient([LLMRateLimitError("429", retry_after=7.0), "ok"])
    await build(inner, clock).generate_text("hi", purpose="t")
    assert clock.sleeps == [7.0]


async def test_retry_after_longer_than_the_cap_gives_up_immediately() -> None:
    clock = FakeClock()
    inner = FakeLLMClient([LLMRateLimitError("429", retry_after=600.0), "ok"])
    with pytest.raises(LLMRateLimitError):
        await build(inner, clock).generate_text("hi", purpose="t")
    assert clock.sleeps == []
    assert len(inner.calls) == 1


async def test_gives_up_after_bounded_attempts() -> None:
    clock = FakeClock()
    inner = FakeLLMClient([LLMTransientError("503")] * 5)
    with pytest.raises(LLMTransientError):
        await build(inner, clock, max_retries=2).generate_text("hi", purpose="t")
    assert len(inner.calls) == 3
    assert len(clock.sleeps) == 2


async def test_non_transient_errors_are_not_retried() -> None:
    clock = FakeClock()
    inner = FakeLLMClient([LLMPermanentError("400 bad request"), "ok"])
    with pytest.raises(LLMPermanentError):
        await build(inner, clock).generate_text("hi", purpose="t")
    assert len(inner.calls) == 1
    assert clock.sleeps == []


class _Hangs(FakeLLMClient):
    async def generate_text(self, *args: object, **kwargs: object):  # type: ignore[override]
        await asyncio.sleep(30)


async def test_timeout_is_retried_then_raised() -> None:
    clock = FakeClock()
    with pytest.raises(LLMTransientError, match="timed out"):
        await build(_Hangs(), clock, max_retries=1, timeout=0.01).generate_text("hi", purpose="t")
    assert len(clock.sleeps) == 1  # one backoff between the two attempts


# --- cache ------------------------------------------------------------------------------------


async def test_cache_miss_then_hit(redis_client: Redis, key_prefix: str) -> None:
    clock = FakeClock()
    inner = FakeLLMClient(["first answer", "should never be used"])
    cache = ResponseCache(redis_client, ttl_seconds=60, prefix=key_prefix)
    llm = build(inner, clock, cache=cache, pricing={"fake-model": ModelPrice(input_per_mtok=1e6)})

    miss = await llm.generate_text("same prompt", purpose="t")
    hit = await llm.generate_text("same prompt", purpose="t")
    other = await llm.generate_text("different prompt", purpose="t")

    assert (miss.cached, miss.cost_usd_estimate > 0) == (False, True)
    assert hit.text == "first answer"
    assert (hit.cached, hit.tokens_in, hit.tokens_out, hit.cost_usd_estimate) == (True, 0, 0, 0.0)
    assert other.text == "should never be used"
    assert len(inner.calls) == 2


async def test_cache_key_depends_on_model_system_and_schema() -> None:
    base = {"kind": "json", "model": "m", "system": None, "prompt": "p", "schema": Job}

    class Other(BaseModel):
        title: str
        extra: int

    assert cache_key(**base) == cache_key(**base)
    assert cache_key(**base) != cache_key(**{**base, "model": "m2"})
    assert cache_key(**base) != cache_key(**{**base, "system": "s"})
    assert cache_key(**base) != cache_key(**{**base, "schema": Other})
    assert cache_key(**base) != cache_key(**{**base, "kind": "text", "schema": None})


async def test_cache_ttl_zero_disables_caching(redis_client: Redis, key_prefix: str) -> None:
    inner = FakeLLMClient(["a", "b"])
    cache = ResponseCache(redis_client, ttl_seconds=0, prefix=key_prefix)
    llm = build(inner, FakeClock(), cache=cache)
    await llm.generate_text("p", purpose="t")
    second = await llm.generate_text("p", purpose="t")
    assert second.text == "b"


async def test_invalid_structured_reply_is_not_left_in_the_cache(
    redis_client: Redis, key_prefix: str
) -> None:
    inner = FakeLLMClient(["not json", '{"title": "ok"}'])
    cache = ResponseCache(redis_client, ttl_seconds=60, prefix=key_prefix)
    llm = build(inner, FakeClock(), cache=cache)

    job, _ = await llm.generate_structured("classify", Job, purpose="t")

    assert job.title == "ok"
    bad_key = cache_key(kind="json", model="fake-model", system=None, prompt="classify", schema=Job)
    assert await cache.get(bad_key) is None


async def test_cached_structured_result_is_reused(redis_client: Redis, key_prefix: str) -> None:
    inner = FakeLLMClient(['{"title": "ok"}'])
    cache = ResponseCache(redis_client, ttl_seconds=60, prefix=key_prefix)
    llm = build(inner, FakeClock(), cache=cache)

    await llm.generate_structured("classify", Job, purpose="t")
    _, second = await llm.generate_structured("classify", Job, purpose="t")

    assert second.cached is True
    assert len(inner.calls) == 1


# --- budget -----------------------------------------------------------------------------------


async def test_token_budget_exceeded_after_the_call_and_blocks_the_next() -> None:
    inner = FakeLLMClient(["x" * 400, "never reached"])
    budget = Budget(max_tokens=50)
    llm = build(inner, FakeClock())

    with pytest.raises(BudgetExceeded):  # the reply itself used ~100 tokens
        await llm.generate_text("p" * 40, purpose="t", budget=budget)
    assert budget.tokens_used > 50

    with pytest.raises(BudgetExceeded):  # already spent: refused before calling
        await llm.generate_text("p", purpose="t", budget=budget)
    assert len(inner.calls) == 1


async def test_cost_budget_uses_the_pricing_table() -> None:
    inner = FakeLLMClient(["x" * 40, "y" * 40])
    pricing = {"fake-model": ModelPrice(input_per_mtok=1_000_000, output_per_mtok=1_000_000)}
    budget = Budget(max_cost_usd=15.0)  # 1 USD per token, ~20 tokens per call
    llm = build(inner, FakeClock(), pricing=pricing)

    with pytest.raises(BudgetExceeded):
        await llm.generate_text("p" * 40, purpose="t", budget=budget)
    assert budget.cost_used == pytest.approx(budget.tokens_used)


async def test_cache_hits_do_not_consume_budget(redis_client: Redis, key_prefix: str) -> None:
    inner = FakeLLMClient(["answer"])
    cache = ResponseCache(redis_client, ttl_seconds=60, prefix=key_prefix)
    llm = build(inner, FakeClock(), cache=cache)
    budget = Budget(max_tokens=1_000)

    await llm.generate_text("p", purpose="t", budget=budget)
    used = budget.tokens_used
    await llm.generate_text("p", purpose="t", budget=budget)

    assert budget.tokens_used == used


# --- rate limiter -----------------------------------------------------------------------------


async def test_rate_limiter_makes_the_next_call_wait(redis_client: Redis, key_prefix: str) -> None:
    clock = FakeClock()
    limiter = RedisRateLimiter(
        redis_client, limit=2, key=key_prefix + "rate", clock=clock.time, sleep=clock.sleep
    )

    await limiter.acquire()
    await limiter.acquire()
    assert clock.sleeps == []  # two slots were free

    await limiter.acquire()  # third must wait for the oldest request to leave the 60s window
    assert clock.sleeps == [pytest.approx(60.0)]


async def test_rate_limiter_is_shared_by_every_client_using_the_same_key(
    redis_client: Redis, key_prefix: str
) -> None:
    clock = FakeClock()

    def limiter() -> RedisRateLimiter:
        return RedisRateLimiter(
            redis_client, limit=1, key=key_prefix + "rate", clock=clock.time, sleep=clock.sleep
        )

    await limiter().acquire()  # "worker A"
    await limiter().acquire()  # "worker B" sees A's request
    assert clock.sleeps == [pytest.approx(60.0)]


async def test_every_attempt_goes_through_the_rate_limiter(
    redis_client: Redis, key_prefix: str
) -> None:
    clock = FakeClock()
    limiter = RedisRateLimiter(
        redis_client, limit=100, key=key_prefix + "rate", clock=clock.time, sleep=clock.sleep
    )
    inner = FakeLLMClient([LLMTransientError("503"), "ok"])
    await build(inner, clock, rate_limiter=limiter).generate_text("p", purpose="t")
    assert await redis_client.zcard(key_prefix + "rate") == 2


# --- tool turns -------------------------------------------------------------------------------


async def test_tool_turns_are_priced_budgeted_and_never_cached(
    redis_client: Redis, key_prefix: str
) -> None:
    call = ToolCall(id="1", name="search_company", arguments={"name": "Acme"})
    inner = FakeLLMClient([[call], [call]])
    cache = ResponseCache(redis_client, ttl_seconds=60, prefix=key_prefix)
    budget = Budget(max_tokens=10_000)
    llm = build(inner, FakeClock(), cache=cache)
    tools = [ToolSpec(name="search_company", description="d", parameters={"type": "object"})]

    for _ in range(2):
        turn = await llm.generate_with_tools(
            [Message.user("find Acme")], tools, purpose="t", budget=budget
        )
        assert turn.tool_calls == [call]
    assert len(inner.calls) == 2
    assert budget.tokens_used > 0


# --- logging ----------------------------------------------------------------------------------


@pytest.fixture
async def cleanup_log_rows(
    committing_session_factory: async_sessionmaker[AsyncSession],
):
    purposes: list[str] = []
    yield purposes
    async with committing_session_factory() as session, session.begin():
        await session.execute(delete(LLMCallLog).where(LLMCallLog.purpose.in_(purposes)))


async def test_each_call_writes_a_log_row_and_a_structlog_event(
    committing_session_factory: async_sessionmaker[AsyncSession],
    cleanup_log_rows: list[str],
    redis_client: Redis,
    key_prefix: str,
) -> None:
    purpose = f"test-{key_prefix}"
    cleanup_log_rows.append(purpose)
    inner = FakeLLMClient(["answer"])
    cache = ResponseCache(redis_client, ttl_seconds=60, prefix=key_prefix)
    pricing = {"fake-fast-model": ModelPrice(input_per_mtok=2.0, output_per_mtok=4.0)}
    llm = build(
        inner,
        FakeClock(),
        cache=cache,
        call_logger=DbCallLogger(committing_session_factory),
        pricing=pricing,
    )

    with structlog.testing.capture_logs() as events:
        await llm.generate_text("hello world", purpose=purpose, tier=ModelTier.FAST)
        await llm.generate_text("hello world", purpose=purpose, tier=ModelTier.FAST)

    assert [e["cached"] for e in events if e["event"] == "llm_call"] == [False, True]

    async with committing_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(LLMCallLog)
                    .where(LLMCallLog.purpose == purpose)
                    .order_by(LLMCallLog.cached)
                )
            )
            .scalars()
            .all()
        )
    live, cached = rows
    assert (live.provider, live.model, live.cached) == ("fake", "fake-fast-model", False)
    assert live.tokens_in > 0 and live.tokens_out > 0
    assert live.cost_usd_estimate > Decimal(0)
    assert (cached.cached, cached.cost_usd_estimate, cached.tokens_in) == (True, Decimal(0), 0)


async def test_a_failing_call_logger_does_not_fail_the_call() -> None:
    class Broken:
        async def record(self, **kwargs: object) -> None:
            raise RuntimeError("db down")

    llm = build(FakeLLMClient(["ok"]), FakeClock(), call_logger=Broken())  # type: ignore[arg-type]
    assert (await llm.generate_text("p", purpose="t")).text == "ok"
