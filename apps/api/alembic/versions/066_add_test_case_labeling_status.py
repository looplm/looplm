"""Add test_case_labeling_status (manual 'labeling complete' flag per test case).

Revision ID: 066
Revises: 065
Create Date: 2026-06-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = '066'
down_revision: Union[str, None] = '065'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _has_table("test_case_labeling_status"):
        return
    op.create_table(
        "test_case_labeling_status",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("test_id", sa.String(512), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "marked_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("project_id", "test_id", name="uq_labeling_status_project_test"),
    )
    op.create_index("ix_test_case_labeling_status_project_id", "test_case_labeling_status", ["project_id"])
    op.create_index("idx_labeling_status_project", "test_case_labeling_status", ["project_id"])


def downgrade() -> None:
    op.drop_index("idx_labeling_status_project", table_name="test_case_labeling_status")
    op.drop_index("ix_test_case_labeling_status_project_id", table_name="test_case_labeling_status")
    op.drop_table("test_case_labeling_status")
