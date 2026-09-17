from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import LLMCallLog
from app.llm.types import LLMResult


class CallLogger(Protocol):
    async def record(self, *, provider: str, purpose: str, result: LLMResult) -> None: ...


class DbCallLogger:
    """Writes one llm_call_log row per call, in its own transaction (so it survives a caller's
    rollback)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, *, provider: str, purpose: str, result: LLMResult) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(
                LLMCallLog(
                    provider=provider,
                    model=result.model,
                    purpose=purpose,
                    tokens_in=result.tokens_in,
                    tokens_out=result.tokens_out,
                    latency_ms=result.latency_ms,
                    cost_usd_estimate=Decimal(str(round(result.cost_usd_estimate, 6))),
                    cached=result.cached,
                )
            )
