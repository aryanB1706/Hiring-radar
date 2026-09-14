from collections.abc import Awaitable, Callable

from fastapi import Request
from sqlalchemy import text

Check = Callable[[], Awaitable[None]]
"""A health check: returns normally if the service is up, raises if not."""


def get_db_check(request: Request) -> Check:
    engine = request.app.state.engine

    async def check() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    return check


def get_redis_check(request: Request) -> Check:
    client = request.app.state.redis

    async def check() -> None:
        await client.ping()

    return check
