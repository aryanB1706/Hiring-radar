"""LangChain tools for finding similar saved jobs."""

from typing import Any

from langchain_core.tools import tool
from sqlalchemy import text

from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.services.job_embeddings import embed_text, embedding_literal

logger = get_logger("app.tools.job_search")


@tool
def search_similar_jobs(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search existing jobs using PostgreSQL pgvector cosine similarity."""
    if not str(query).strip():
        return []

    try:
        safe_limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        safe_limit = 5

    vector = embedding_literal(embed_text(str(query)))
    db = SessionLocal()
    try:
        rows = (
            db.execute(
                text(
                    """
                    SELECT l.id AS lead_id,
                           l.company_name,
                           l.role_title,
                           l.skills,
                           l.location,
                           l.application_url,
                           e.embedding <=> CAST(:embedding AS vector) AS distance
                    FROM job_embedding e
                    JOIN lead l ON l.id = e.lead_id
                    ORDER BY e.embedding <=> CAST(:embedding AS vector)
                    LIMIT :limit
                    """
                ),
                {"embedding": vector, "limit": safe_limit},
            )
            .mappings()
            .all()
        )
        return [
            {
                "lead_id": str(row["lead_id"]),
                "company": row["company_name"],
                "role": row["role_title"],
                "skills": row["skills"] or [],
                "location": row["location"],
                "application_url": row["application_url"],
                "distance": round(float(row["distance"]), 4),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("search_similar_jobs_failed", error=type(exc).__name__)
        return []
    finally:
        db.close()
