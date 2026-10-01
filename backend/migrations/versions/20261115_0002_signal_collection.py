"""Add signal collection fields, RSS source kind, and dedupe indexes.

Revision ID: 20261115_0002
Revises: 20260928_0001
Create Date: 2026-11-15 08:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261115_0002"
down_revision: str | None = "20260928_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE source_kind ADD VALUE IF NOT EXISTS 'rss'")

    op.add_column("post", sa.Column("title", sa.String(500), nullable=True))

    op.drop_index("ix_post_content_hash", table_name="post")
    op.create_index("uq_post_content_hash", "post", ["content_hash"], unique=True)
    op.create_index("uq_post_url", "post", ["url"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_post_url", table_name="post")
    op.drop_index("uq_post_content_hash", table_name="post")
    op.create_index("ix_post_content_hash", "post", ["content_hash"])

    op.drop_column("post", "title")
