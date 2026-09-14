import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Neither call connects yet; connections open on first use.
    app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.redis = Redis.from_url(settings.redis_url)
    yield
    await app.state.engine.dispose()
    await app.state.redis.aclose()


async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    structlog.get_logger().info(
        "request", method=request.method, path=request.url.path, status=response.status_code
    )
    return response


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.app_env)
    app = FastAPI(title="Hiring Radar", lifespan=lifespan)
    app.middleware("http")(request_id_middleware)
    app.include_router(health_router, prefix="/api")
    return app
