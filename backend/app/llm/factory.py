import asyncio

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.llm.base import LLMClient
from app.llm.cache import ResponseCache
from app.llm.call_log import DbCallLogger
from app.llm.errors import LLMConfigError
from app.llm.gemini import GeminiClient
from app.llm.rate_limit import RedisRateLimiter
from app.llm.reliable import ReliableLLMClient
from app.llm.retry import RetryPolicy


def build_llm_client(
    settings: Settings,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> LLMClient:
    """The one place a provider is chosen. Business code asks for an LLMClient and gets this."""
    if settings.gemini_api_key is None:
        raise LLMConfigError("GEMINI_API_KEY is not set")
    inner = GeminiClient(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
        fast_model=settings.gemini_fast_model,
    )
    return ReliableLLMClient(
        inner,
        retry=RetryPolicy(max_retries=settings.llm_max_retries),
        timeout_seconds=settings.llm_timeout_seconds,
        rate_limiter=RedisRateLimiter(redis, limit=settings.llm_rpm_limit, sleep=asyncio.sleep),
        cache=ResponseCache(redis, settings.llm_cache_ttl_seconds),
        call_logger=DbCallLogger(session_factory) if session_factory else None,
        pricing=settings.llm_pricing,
    )
