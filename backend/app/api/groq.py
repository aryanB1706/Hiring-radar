"""Groq connectivity test endpoint."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.groq import get_llm

router = APIRouter(prefix="/api/groq", tags=["groq"])
logger = get_logger("app.api.groq")


class GroqTestResponse(BaseModel):
    """Result of a Groq connectivity check."""

    status: str
    model: str
    reply: str


@router.get(
    "/test",
    response_model=GroqTestResponse,
    responses={503: {"description": "Groq is not configured or unreachable"}},
)
def test_groq() -> GroqTestResponse:
    """Send a tiny prompt to Groq and return the model response."""
    try:
        llm = get_llm()
        message = llm.invoke("Reply with exactly one word: ok")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("groq_connectivity_failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Groq connectivity check failed",
        ) from exc

    settings = get_settings()
    return GroqTestResponse(
        status="ok",
        model=settings.GROQ_MODEL,
        reply=str(message.content).strip(),
    )
