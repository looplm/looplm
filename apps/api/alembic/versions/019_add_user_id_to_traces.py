"""Add user_id column to traces table.

Revision ID: 019_add_user_id_to_traces
Revises: 018_add_json_imports_table
Create Date: 2026-03-17
"""

import sqlalchemy as sa
from alembic import op

revision = "019_add_user_id_to_traces"
down_revision = "018_add_json_imports_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("traces", sa.Column("user_id", sa.String(512), nullable=True))
    op.create_index(
        "idx_traces_user_id",
        "traces",
        ["user_id"],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_traces_user_id", table_name="traces")
    op.drop_column("traces", "user_id")
