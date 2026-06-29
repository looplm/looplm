"""Non-human annotator identity on chunk relevance labels.

Adds a nullable ``annotator`` column to chunk_relevance_labels so a label can be attributed to
a non-human judge (the built-in "AI" annotator) instead of a user. Human labels leave it NULL
(their annotator is ``labeled_by``); AI labels set it (and leave ``labeled_by`` NULL). This
lets a single human + the AI judge produce inter-annotator agreement without a second reviewer.

Revision ID: 070
Revises: 069
Create Date: 2026-06-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '070'
down_revision: Union[str, None] = '069'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "chunk_relevance_labels" not in (sa.inspect(op.get_bind()).get_table_names()):
        return
    if "annotator" not in _columns("chunk_relevance_labels"):
        op.add_column(
            "chunk_relevance_labels",
            sa.Column("annotator", sa.String(length=64), nullable=True),
        )


def downgrade() -> None:
    if "annotator" in _columns("chunk_relevance_labels"):
        op.drop_column("chunk_relevance_labels", "annotator")
