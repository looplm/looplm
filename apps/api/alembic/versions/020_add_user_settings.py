"""Add settings JSONB column to users table.

Revision ID: 020_add_user_settings
Revises: 019_add_user_id_to_traces
Create Date: 2026-03-18
"""

import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019_add_user_id_to_traces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("users", "settings")
