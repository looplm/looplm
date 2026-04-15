"""Add sync progress fields to integrations.

Revision ID: 002_add_sync_progress_fields
Revises: 001_add_last_sync_error
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa

revision = "002_add_sync_progress_fields"
down_revision = "001_add_last_sync_error"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("integrations", sa.Column("sync_progress_current", sa.Integer(), nullable=True))
    op.add_column("integrations", sa.Column("sync_progress_total", sa.Integer(), nullable=True))
    op.add_column("integrations", sa.Column("sync_started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("integrations", "sync_started_at")
    op.drop_column("integrations", "sync_progress_total")
    op.drop_column("integrations", "sync_progress_current")
