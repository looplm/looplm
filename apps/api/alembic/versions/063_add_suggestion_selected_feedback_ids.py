"""Add filter_selected_feedback_ids to feedback_suggestion_runs (hand-picked feedback).

Revision ID: 063
Revises: 062
Create Date: 2026-06-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = '063'
down_revision: Union[str, None] = '062'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    # Guard against reruns in dev environments (see CLAUDE.md on startup create_all).
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(c["name"] == column for c in columns)


def upgrade() -> None:
    if not _has_column("feedback_suggestion_runs", "filter_selected_feedback_ids"):
        op.add_column(
            "feedback_suggestion_runs",
            sa.Column("filter_selected_feedback_ids", postgresql.JSONB(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("feedback_suggestion_runs", "filter_selected_feedback_ids")
