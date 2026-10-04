"""Add pgvector job embedding search.

Revision ID: 20261115_0004
Revises: 20261115_0003
Create Date: 2026-11-15 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261115_0004"
down_revision: str | None = "20261115_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE job_embedding (
            lead_id UUID PRIMARY KEY REFERENCES lead(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            embedding vector(384) NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_job_embedding_embedding
        ON job_embedding USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_embedding")
