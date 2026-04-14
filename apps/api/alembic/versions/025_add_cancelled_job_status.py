"""Add 'cancelled' to eval_job_status enum.

Revision ID: 025_add_cancelled_job_status
Revises: 024_add_eval_reports
Create Date: 2026-03-19
"""

from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE eval_job_status ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values; this is a no-op
    pass
