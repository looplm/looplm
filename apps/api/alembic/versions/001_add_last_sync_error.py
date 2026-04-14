"""Add last_sync_error column to integrations.

Revision ID: 001_add_last_sync_error
Revises:
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa

revision = "001_add_last_sync_error"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("integrations", sa.Column("last_sync_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("integrations", "last_sync_error")
