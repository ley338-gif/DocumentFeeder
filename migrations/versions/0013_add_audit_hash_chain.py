"""add tamper-evident audit hash chain

Revision ID: 0013
Revises: 0012
"""

from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("chain_index", sa.BigInteger()))
    op.add_column("audit_events", sa.Column("previous_hash", sa.String(64)))
    op.add_column("audit_events", sa.Column("entry_hash", sa.String(64)))
    op.create_index(
        "ix_audit_events_chain_index",
        "audit_events",
        ["chain_index"],
        unique=True,
    )
    op.create_index(
        "ix_audit_events_entry_hash",
        "audit_events",
        ["entry_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_entry_hash", table_name="audit_events")
    op.drop_index("ix_audit_events_chain_index", table_name="audit_events")
    op.drop_column("audit_events", "entry_hash")
    op.drop_column("audit_events", "previous_hash")
    op.drop_column("audit_events", "chain_index")
