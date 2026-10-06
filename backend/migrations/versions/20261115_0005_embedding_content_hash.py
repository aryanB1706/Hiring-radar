"""Track embedding content hashes to avoid duplicate generation.

Revision ID: 20261115_0005
Revises: 20261115_0004
Create Date: 2026-11-15 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261115_0005"
down_revision: str | None = "20261115_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job_embedding", sa.Column("content_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("job_embedding", "content_hash")
