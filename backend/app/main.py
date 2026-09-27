"""Main FastAPI application factory and entrypoint."""

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware binding unique request_id to structlog contextvars for every HTTP request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    settings = get_settings()
    logger = get_logger("app.main")
    logger.info("application_started", env=settings.APP_ENV)
    yield
    logger.info("application_shutdown", env=settings.APP_ENV)


def create_app() -> FastAPI:
    """Create and configure an instance of the FastAPI application."""
    settings = get_settings()
    setup_logging(app_env=settings.APP_ENV, log_level=settings.LOG_LEVEL)

    app = FastAPI(
        title="Hiring Radar API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)
    app.include_router(health_router)

    return app


app = create_app()
