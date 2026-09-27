"""Health check API endpoints."""

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db, ping_db

router = APIRouter(prefix="/api", tags=["health"])


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str
    db: str


def verify_db_connection(db: Session = Depends(get_db)) -> bool:
    """Dependency that checks if the database is reachable."""
    return ping_db(db)


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={
        200: {"description": "System and database are healthy"},
        503: {"description": "Database or dependent services are unavailable"},
    },
)
def health_check(
    response: Response,
    db_ok: bool = Depends(verify_db_connection),
) -> HealthResponse:
    """Return health status of the application and PostgreSQL."""
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="unhealthy", db="disconnected")

    return HealthResponse(status="ok", db="connected")
