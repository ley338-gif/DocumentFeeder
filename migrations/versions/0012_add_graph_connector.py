"""add Microsoft Graph connector settings

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("target_systems", sa.Column("graph_tenant_id", sa.String(200)))
    op.add_column("target_systems", sa.Column("graph_client_id", sa.String(200)))
    op.add_column("target_systems", sa.Column("graph_client_secret", sa.Text()))
    op.add_column("target_systems", sa.Column("graph_drive_id", sa.String(300)))
    op.add_column(
        "target_systems",
        sa.Column(
            "graph_folder",
            sa.Text(),
            nullable=False,
            server_default="DocumentCore",
        ),
    )


def downgrade() -> None:
    op.drop_column("target_systems", "graph_folder")
    op.drop_column("target_systems", "graph_drive_id")
    op.drop_column("target_systems", "graph_client_secret")
    op.drop_column("target_systems", "graph_client_id")
    op.drop_column("target_systems", "graph_tenant_id")
