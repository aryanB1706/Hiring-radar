"""Sentence-transformer embeddings and pgvector job indexing."""

import hashlib
from functools import lru_cache
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Lead
from app.llm.classifier import JobClassification

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384


@lru_cache(maxsize=1)
def get_embedding_model() -> Any:
    """Load and cache the sentence-transformers model."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def embed_text(value: str) -> list[float]:
    """Create a normalized 384-dimensional semantic embedding."""
    model = get_embedding_model()
    vector = model.encode(value, normalize_embeddings=True)
    return vector.tolist()


def embedding_literal(vector: list[float]) -> str:
    """Convert a vector list to the text format accepted by pgvector."""
    return "[" + ",".join(f"{item:.8f}" for item in vector) + "]"


def content_hash(value: str) -> str:
    """Return a stable hash used to skip unchanged job embeddings."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def job_embedding_text(
    result: JobClassification,
    description: str | None = None,
) -> str:
    """Build the searchable text for a job title, description, and skills."""
    parts = [
        f"Company: {result.company_name}" if result.company_name else None,
        f"Title: {result.job_title}" if result.job_title else None,
        f"Skills: {', '.join(result.skills)}" if result.skills else None,
        f"Description: {description[:4000]}" if description else None,
        f"Experience: {result.experience_level}" if result.experience_level else None,
        f"Location: {result.location}" if result.location else None,
        f"Job type: {result.job_type}" if result.job_type != "unknown" else None,
    ]
    return "\n".join(part for part in parts if part)


def index_job(
    db: Session,
    lead: Lead,
    result: JobClassification,
    description: str | None = None,
) -> bool:
    """Generate and store a job embedding unless the content is unchanged."""
    content = job_embedding_text(result, description)
    if not content:
        return False

    digest = content_hash(content)
    existing_hash = db.execute(
        text("SELECT content_hash FROM job_embedding WHERE lead_id = :lead_id"),
        {"lead_id": lead.id},
    ).scalar()
    if existing_hash == digest:
        return False

    db.execute(
        text(
            """
            INSERT INTO job_embedding (lead_id, content, content_hash, embedding)
            VALUES (:lead_id, :content, :content_hash, CAST(:embedding AS vector))
            ON CONFLICT (lead_id) DO UPDATE
            SET content = EXCLUDED.content,
                content_hash = EXCLUDED.content_hash,
                embedding = EXCLUDED.embedding
            """
        ),
        {
            "lead_id": lead.id,
            "content": content,
            "content_hash": digest,
            "embedding": embedding_literal(embed_text(content)),
        },
    )
    db.commit()
    return True
