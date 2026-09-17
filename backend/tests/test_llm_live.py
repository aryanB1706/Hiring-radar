"""Optional live smoke test: one real Gemini call, then the same call again from the cache.

Run with `make migrate && cd backend && .venv/bin/pytest -m live -s` after setting GEMINI_API_KEY
in .env. Rows land in the dev database's llm_call_log.
"""

import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.models import LLMCallLog
from app.db.session import make_session_factory
from app.llm import ModelTier
from app.llm.factory import build_llm_client

settings = get_settings()

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(settings.gemini_api_key is None, reason="GEMINI_API_KEY is not set"),
]


async def test_real_call_is_logged_and_the_repeat_is_served_from_cache() -> None:
    engine = create_async_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    session_factory = make_session_factory(engine)
    llm = build_llm_client(settings, redis, session_factory)
    purpose = f"live-smoke-{uuid.uuid4().hex[:8]}"
    prompt = f"Reply with exactly one word: pong ({purpose})"  # unique, so the 1st call is a miss

    try:
        first = await llm.generate_text(prompt, purpose=purpose, tier=ModelTier.FAST)
        second = await llm.generate_text(prompt, purpose=purpose, tier=ModelTier.FAST)

        assert first.cached is False and first.text.strip()
        assert second.cached is True and second.text == first.text
        async with session_factory() as session:
            rows = (
                (await session.execute(select(LLMCallLog).where(LLMCallLog.purpose == purpose)))
                .scalars()
                .all()
            )
        assert sorted(r.cached for r in rows) == [False, True]
        print(f"\nlive call ok: model={first.model} tokens={first.tokens_in}/{first.tokens_out}")
    finally:
        await redis.aclose()
        await engine.dispose()
