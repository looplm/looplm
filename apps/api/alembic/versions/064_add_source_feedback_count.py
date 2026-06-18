"""Add source_feedback_count to feedback_suggestion_runs (explains dedup gap).

Revision ID: 064
Revises: 063
Create Date: 2026-06-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '064'
down_revision: Union[str, None] = '063'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    # Guard against reruns in dev environments (see CLAUDE.md on startup create_all).
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(c["name"] == column for c in columns)


def upgrade() -> None:
    if not _has_column("feedback_suggestion_runs", "source_feedback_count"):
        op.add_column(
            "feedback_suggestion_runs",
            sa.Column(
                "source_feedback_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    op.drop_column("feedback_suggestion_runs", "source_feedback_count")
