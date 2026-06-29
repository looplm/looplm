"""Graded chunk relevance (0..3) replacing the binary relevant flag.

Relevance judging moves from boolean (relevant / not) to a graded 0..3 scale (0 irrelevant,
1 marginally relevant, 2 relevant, 3 highly relevant). The boolean ``relevant`` column on
chunk_relevance_labels and chunk_gold_labels is replaced by an integer ``relevance``. Existing
labels are dropped (the scales aren't equivalent and the project chose a clean restart), so no
value mapping is attempted.

Revision ID: 069
Revises: 068
Create Date: 2026-06-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '069'
down_revision: Union[str, None] = '068'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _switch_to_graded(table: str) -> None:
    if not _has_table(table):
        return
    # Existing binary judgments can't be mapped onto the graded scale, so start clean.
    op.execute(sa.text(f"DELETE FROM {table}"))
    cols = _columns(table)
    if "relevant" in cols:
        op.drop_column(table, "relevant")
    if "relevance" not in cols:
        # Table is empty after the delete, so a NOT NULL column needs no server default.
        op.add_column(table, sa.Column("relevance", sa.Integer(), nullable=False))


def upgrade() -> None:
    _switch_to_graded("chunk_relevance_labels")
    _switch_to_graded("chunk_gold_labels")


def _switch_to_binary(table: str) -> None:
    if not _has_table(table):
        return
    op.execute(sa.text(f"DELETE FROM {table}"))
    cols = _columns(table)
    if "relevance" in cols:
        op.drop_column(table, "relevance")
    if "relevant" not in cols:
        op.add_column(table, sa.Column("relevant", sa.Boolean(), nullable=False))


def downgrade() -> None:
    _switch_to_binary("chunk_relevance_labels")
    _switch_to_binary("chunk_gold_labels")
