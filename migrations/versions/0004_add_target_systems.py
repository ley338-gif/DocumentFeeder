"""Add target systems and job target selection.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "target_systems",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("endpoint_url", sa.Text(), nullable=True),
        sa.Column("bearer_token", sa.Text(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_target_systems_is_default", "target_systems", ["is_default"])
    op.add_column("document_jobs", sa.Column("target_system_id", sa.String(length=36)))
    op.create_index("ix_document_jobs_target_system_id", "document_jobs", ["target_system_id"])


def downgrade() -> None:
    op.drop_index("ix_document_jobs_target_system_id", table_name="document_jobs")
    op.drop_column("document_jobs", "target_system_id")
    op.drop_index("ix_target_systems_is_default", table_name="target_systems")
    op.drop_table("target_systems")
