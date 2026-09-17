import hashlib
import json

import structlog
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.llm.types import LLMResult

log = structlog.get_logger()


def cache_key(
    *, kind: str, model: str, system: str | None, prompt: str, schema: type[BaseModel] | None
) -> str:
    """Hash of everything that changes the answer. The schema is fingerprinted, not just named."""
    schema_part = (
        None
        if schema is None
        else [schema.__name__, json.dumps(schema.model_json_schema(), sort_keys=True)]
    )
    payload = json.dumps([kind, model, system, prompt, schema_part])
    return hashlib.sha256(payload.encode()).hexdigest()


class ResponseCache:
    """Redis cache of LLMResult. ttl_seconds <= 0 disables it. Redis errors never fail a call."""

    def __init__(self, redis: Redis, ttl_seconds: int, prefix: str = "llm:cache:") -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self._prefix = prefix

    async def get(self, key: str) -> LLMResult | None:
        if self._ttl <= 0:
            return None
        try:
            raw = await self._redis.get(self._prefix + key)
        except RedisError as exc:
            log.warning("llm_cache_unavailable", op="get", error=repr(exc))
            return None
        return None if raw is None else LLMResult.model_validate_json(raw)

    async def set(self, key: str, result: LLMResult) -> None:
        if self._ttl <= 0:
            return
        try:
            await self._redis.set(self._prefix + key, result.model_dump_json(), ex=self._ttl)
        except RedisError as exc:
            log.warning("llm_cache_unavailable", op="set", error=repr(exc))

    async def delete(self, key: str) -> None:
        try:
            await self._redis.delete(self._prefix + key)
        except RedisError as exc:
            log.warning("llm_cache_unavailable", op="delete", error=repr(exc))
