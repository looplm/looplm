"""Make the evaluator focus (category) optional.

Focus (retrieval / generation) is a hint, not required — a custom evaluator may target neither.
Drop the NOT NULL constraint and the 'generation' server default so an evaluator can be left
unassigned (NULL). Existing values are preserved.

Revision ID: 073
Revises: 072
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '073'
down_revision: Union[str, None] = '072'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "category" not in _columns("evaluators"):
        return
    op.alter_column(
        "evaluators",
        "category",
        existing_type=sa.String(length=32),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    if "category" not in _columns("evaluators"):
        return
    op.execute("UPDATE evaluators SET category = 'generation' WHERE category IS NULL")
    op.alter_column(
        "evaluators",
        "category",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="generation",
    )
