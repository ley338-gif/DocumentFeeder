"""Add persistent processing queue fields.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_jobs",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "document_jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "document_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("document_jobs", sa.Column("worker_id", sa.String(length=200), nullable=True))
    op.add_column("document_jobs", sa.Column("last_error", sa.Text(), nullable=True))
    op.create_index(
        "ix_document_jobs_queue",
        "document_jobs",
        ["status", "next_attempt_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_document_jobs_queue", table_name="document_jobs")
    op.drop_column("document_jobs", "last_error")
    op.drop_column("document_jobs", "worker_id")
    op.drop_column("document_jobs", "lease_expires_at")
    op.drop_column("document_jobs", "next_attempt_at")
    op.drop_column("document_jobs", "attempt_count")
