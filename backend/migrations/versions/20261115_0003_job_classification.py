"""Add job classification fields to leads.

Revision ID: 20261115_0003
Revises: 20261115_0002
Create Date: 2026-11-15 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261115_0003"
down_revision: str | None = "20261115_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("lead", sa.Column("job_type", sa.String(50), nullable=True))
    op.add_column("lead", sa.Column("application_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("lead", "application_url")
    op.drop_column("lead", "job_type")
