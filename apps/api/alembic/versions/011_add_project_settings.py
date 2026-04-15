"""Add settings JSONB column to projects table.

Revision ID: 011_add_project_settings
Revises: 010_add_eval_jobs
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "011_add_project_settings"
down_revision = "010_add_eval_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("settings", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("projects", "settings")
