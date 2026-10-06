"""Add job seeker profiles and job expiry tracking.

Revision ID: 20261115_0006
Revises: 20261115_0005
Create Date: 2026-11-15 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261115_0006"
down_revision: str | None = "20261115_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_seeker",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("skills", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("preferred_roles", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("experience_level", sa.String(length=50), nullable=True),
        sa.Column("preferred_job_type", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "lead",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lead", "expires_at")
    op.drop_table("job_seeker")
