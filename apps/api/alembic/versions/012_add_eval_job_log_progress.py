"""Add log and progress columns to eval_jobs table.

Revision ID: 012_add_eval_job_log_progress
Revises: 011_add_project_settings
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa

revision = "012_add_eval_job_log_progress"
down_revision = "011_add_project_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("eval_jobs", sa.Column("log", sa.Text, nullable=True))
    op.add_column("eval_jobs", sa.Column("progress_current", sa.Integer, nullable=True))
    op.add_column("eval_jobs", sa.Column("progress_total", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("eval_jobs", "progress_total")
    op.drop_column("eval_jobs", "progress_current")
    op.drop_column("eval_jobs", "log")
