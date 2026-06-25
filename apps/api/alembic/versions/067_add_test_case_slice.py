"""Add risk slice (broad|safety|adversarial) to test_case_labeling_status.

Revision ID: 067
Revises: 066
Create Date: 2026-06-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '067'
down_revision: Union[str, None] = '066'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("test_case_labeling_status", "slice"):
        op.add_column(
            "test_case_labeling_status",
            sa.Column("slice", sa.String(32), nullable=True),
        )


def downgrade() -> None:
    if _has_column("test_case_labeling_status", "slice"):
        op.drop_column("test_case_labeling_status", "slice")
