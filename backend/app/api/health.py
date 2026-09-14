from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import Check, get_db_check, get_redis_check

router = APIRouter()
log = structlog.get_logger()


class HealthResponse(BaseModel):
    status: str
    db: str
    redis: str


async def _probe(name: str, check: Check) -> str:
    try:
        await check()
    except Exception as exc:
        log.warning("health_check_failed", dependency=name, error=repr(exc))
        return "down"
    return "ok"


@router.get("/health", response_model=HealthResponse)
async def health(
    db_check: Annotated[Check, Depends(get_db_check)],
    redis_check: Annotated[Check, Depends(get_redis_check)],
) -> JSONResponse:
    db = await _probe("db", db_check)
    redis = await _probe("redis", redis_check)
    healthy = db == "ok" and redis == "ok"
    body = HealthResponse(status="ok" if healthy else "degraded", db=db, redis=redis)
    return JSONResponse(body.model_dump(), status_code=200 if healthy else 503)
