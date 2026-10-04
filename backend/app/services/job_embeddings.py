"""Deterministic text embeddings and pgvector job indexing."""

import hashlib
import math
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Lead
from app.llm.classifier import JobClassification

EMBEDDING_DIMENSIONS = 384
_WORD_PATTERN = re.compile(r"[a-z0-9_+#.]+")


def embed_text(value: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    """Create a small deterministic hashing embedding for local search."""
    vector = [0.0] * dimensions
    for word in _WORD_PATTERN.findall(value.lower()):
        digest = hashlib.sha256(word.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    length = math.sqrt(sum(item * item for item in vector))
    if length == 0:
        return vector
    return [item / length for item in vector]


def embedding_literal(vector: list[float]) -> str:
    """Convert a vector list to the text format accepted by pgvector."""
    return "[" + ",".join(f"{item:.8f}" for item in vector) + "]"


def job_embedding_text(result: JobClassification) -> str:
    """Build the text that represents one job in the vector index."""
    parts = [
        result.company_name,
        result.job_title,
        " ".join(result.skills),
        result.experience_level,
        result.location,
        result.job_type if result.job_type != "unknown" else None,
    ]
    return " | ".join(part for part in parts if part)


def index_job(db: Session, lead: Lead, result: JobClassification) -> None:
    """Insert or update the pgvector embedding for a saved job."""
    content = job_embedding_text(result)
    if not content:
        return

    db.execute(
        text(
            """
            INSERT INTO job_embedding (lead_id, content, embedding)
            VALUES (:lead_id, :content, CAST(:embedding AS vector))
            ON CONFLICT (lead_id) DO UPDATE
            SET content = EXCLUDED.content,
                embedding = EXCLUDED.embedding
            """
        ),
        {
            "lead_id": lead.id,
            "content": content,
            "embedding": embedding_literal(embed_text(content)),
        },
    )
    db.commit()
