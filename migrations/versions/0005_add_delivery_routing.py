"""Add filesystem templates and delivery routing rules.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("target_systems", sa.Column("directory", sa.String(300), nullable=True))
    op.add_column("target_systems", sa.Column("path_template", sa.Text(), nullable=True))
    op.execute("UPDATE target_systems SET directory='output', path_template='{document_type}/{job_id}'")
    op.alter_column("target_systems", "directory", nullable=False)
    op.alter_column("target_systems", "path_template", nullable=False)
    op.add_column("document_jobs", sa.Column("delivery_path_template", sa.Text()))
    op.create_table(
        "delivery_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("target_system_id", sa.String(36), nullable=False),
        sa.Column("path_template", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_delivery_rules_document_type", "delivery_rules", ["document_type"])
    op.create_index("ix_delivery_rules_target_system_id", "delivery_rules", ["target_system_id"])


def downgrade() -> None:
    op.drop_table("delivery_rules")
    op.drop_column("document_jobs", "delivery_path_template")
    op.drop_column("target_systems", "path_template")
    op.drop_column("target_systems", "directory")
