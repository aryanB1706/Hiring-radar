import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Sequence

import structlog
from pydantic import BaseModel

from app.llm.base import LLMClient
from app.llm.budget import Budget
from app.llm.cache import ResponseCache, cache_key
from app.llm.call_log import CallLogger
from app.llm.errors import LLMTransientError
from app.llm.pricing import ModelPrice, estimate_cost
from app.llm.rate_limit import RedisRateLimiter
from app.llm.retry import RetryPolicy, retry_transient
from app.llm.types import AssistantTurn, LLMResult, Message, ModelTier, ToolSpec

log = structlog.get_logger()


class ReliableLLMClient(LLMClient):
    """Decorator that adds reliability to ANY LLMClient, so providers stay single-attempt.

    Per call: budget check -> cache lookup -> [rate limit -> provider call with timeout] retried on
    transient errors -> price it -> cache it -> log it -> charge the budget.
    """

    def __init__(
        self,
        inner: LLMClient,
        *,
        retry: RetryPolicy,
        timeout_seconds: float,
        rate_limiter: RedisRateLimiter | None = None,
        cache: ResponseCache | None = None,
        call_logger: CallLogger | None = None,
        pricing: dict[str, ModelPrice] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._inner = inner
        self._retry = retry
        self._timeout = timeout_seconds
        self._rate_limiter = rate_limiter
        self._cache = cache
        self._call_logger = call_logger
        self._pricing = pricing or {}
        self._sleep = sleep
        self._rng = rng or random.Random()
        self.provider = inner.provider

    def model_for(self, tier: ModelTier) -> str:
        return self._inner.model_for(tier)

    async def generate_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        purpose: str,
        tier: ModelTier = ModelTier.DEFAULT,
        budget: Budget | None = None,
    ) -> LLMResult:
        key = cache_key(
            kind="text",
            model=self.model_for(tier),
            system=system,
            prompt=prompt,
            schema=None,
        )
        if (hit := await self._lookup(key, purpose, budget)) is not None:
            return hit
        return await self._execute(
            lambda: self._inner.generate_text(prompt, system=system, purpose=purpose, tier=tier),
            purpose=purpose,
            budget=budget,
            store_key=key,
            get_result=lambda r: r,
            set_result=lambda _, new: new,
        )

    async def generate_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system: str | None = None,
        purpose: str,
        tier: ModelTier = ModelTier.DEFAULT,
        budget: Budget | None = None,
    ) -> LLMResult:
        key = self._json_key(prompt, schema, system, tier)
        if (hit := await self._lookup(key, purpose, budget)) is not None:
            return hit
        return await self._execute(
            lambda: self._inner.generate_json(
                prompt, schema, system=system, purpose=purpose, tier=tier
            ),
            purpose=purpose,
            budget=budget,
            store_key=key,
            get_result=lambda r: r,
            set_result=lambda _, new: new,
        )

    async def generate_with_tools(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        system: str | None = None,
        purpose: str,
        tier: ModelTier = ModelTier.DEFAULT,
        budget: Budget | None = None,
    ) -> AssistantTurn:
        # Tool turns depend on a growing history, so they are never cached.
        return await self._execute(
            lambda: self._inner.generate_with_tools(
                messages, tools, system=system, purpose=purpose, tier=tier
            ),
            purpose=purpose,
            budget=budget,
            store_key=None,
            get_result=lambda t: t.result,
            set_result=lambda t, new: t.model_copy(update={"result": new}),
        )

    async def invalidate_cached_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system: str | None,
        tier: ModelTier,
    ) -> None:
        if self._cache is not None:
            await self._cache.delete(self._json_key(prompt, schema, system, tier))

    def _json_key(
        self, prompt: str, schema: type[BaseModel], system: str | None, tier: ModelTier
    ) -> str:
        return cache_key(
            kind="json", model=self.model_for(tier), system=system, prompt=prompt, schema=schema
        )

    async def _lookup(self, key: str, purpose: str, budget: Budget | None) -> LLMResult | None:
        """Serve from cache if possible. A hit costs nothing: no tokens, no cost, no rate limit."""
        if budget is not None:
            budget.check()
        if self._cache is None:
            return None
        started = time.monotonic()
        hit = await self._cache.get(key)
        if hit is None:
            return None
        served = hit.model_copy(
            update={
                "cached": True,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd_estimate": 0.0,
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
        )
        await self._record(purpose, served)
        return served

    async def _execute[T](
        self,
        call: Callable[[], Awaitable[T]],
        *,
        purpose: str,
        budget: Budget | None,
        store_key: str | None,
        get_result: Callable[[T], LLMResult],
        set_result: Callable[[T, LLMResult], T],
    ) -> T:
        if budget is not None:
            budget.check()
        output = await retry_transient(
            lambda: self._attempt(call), self._retry, sleep=self._sleep, rng=self._rng
        )
        result = get_result(output)
        result = result.model_copy(
            update={
                "cost_usd_estimate": estimate_cost(
                    self._pricing, result.model, result.tokens_in, result.tokens_out
                )
            }
        )
        if store_key is not None and self._cache is not None:
            await self._cache.set(store_key, result)
        await self._record(purpose, result)
        if budget is not None:
            budget.charge(result)
        return set_result(output, result)

    async def _attempt[T](self, call: Callable[[], Awaitable[T]]) -> T:
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire()
        try:
            return await asyncio.wait_for(call(), timeout=self._timeout)
        except TimeoutError as exc:
            raise LLMTransientError(f"LLM call timed out after {self._timeout}s") from exc

    async def _record(self, purpose: str, result: LLMResult) -> None:
        log.info(
            "llm_call",
            provider=self.provider,
            model=result.model,
            purpose=purpose,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            latency_ms=result.latency_ms,
            cost_usd_estimate=result.cost_usd_estimate,
            cached=result.cached,
        )
        if self._call_logger is None:
            return
        try:
            await self._call_logger.record(provider=self.provider, purpose=purpose, result=result)
        except Exception as exc:  # a logging failure must not fail the LLM call
            log.error("llm_call_log_write_failed", error=repr(exc))
