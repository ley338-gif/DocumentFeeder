"""add HTTP connector health and response settings

Revision ID: 0011
Revises: 0010
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("target_systems", sa.Column("healthcheck_url", sa.Text(), nullable=True))
    op.add_column(
        "target_systems",
        sa.Column("max_response_bytes", sa.Integer(), server_default="65536", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("target_systems", "max_response_bytes")
    op.drop_column("target_systems", "healthcheck_url")
