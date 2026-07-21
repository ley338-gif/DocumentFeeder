"""Create document jobs table.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("document_type", sa.String(length=100), nullable=False),
        sa.Column("routing_reference", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("review_history", sa.JSON(), nullable=False),
        sa.Column("text_preview", sa.Text(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_jobs_sha256", "document_jobs", ["sha256"], unique=True)
    op.create_index("ix_document_jobs_status", "document_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_document_jobs_status", table_name="document_jobs")
    op.drop_index("ix_document_jobs_sha256", table_name="document_jobs")
    op.drop_table("document_jobs")
