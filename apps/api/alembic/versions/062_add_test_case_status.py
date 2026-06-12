"""Add status + status_note to test_cases (needs-work flag).

Revision ID: 062
Revises: 061
Create Date: 2026-06-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '062'
down_revision: Union[str, None] = '061'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    # Guard against reruns in dev environments (see CLAUDE.md on startup create_all).
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(c["name"] == column for c in columns)


def upgrade() -> None:
    if not _has_column("test_cases", "status"):
        op.add_column(
            "test_cases",
            sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'active'")),
        )
    if not _has_column("test_cases", "status_note"):
        op.add_column("test_cases", sa.Column("status_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("test_cases", "status_note")
    op.drop_column("test_cases", "status")
