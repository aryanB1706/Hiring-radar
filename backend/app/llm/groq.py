"""Reusable Groq chat model initializer."""

from functools import lru_cache

from langchain_groq import ChatGroq

from app.core.config import get_settings


@lru_cache
def get_llm() -> ChatGroq:
    """Return a cached ChatGroq client built from environment settings."""
    settings = get_settings()
    if not settings.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not set")

    return ChatGroq(
        model=settings.GROQ_MODEL,
        api_key=settings.GROQ_API_KEY,
        temperature=0,
        timeout=30,
        max_retries=2,
    )
