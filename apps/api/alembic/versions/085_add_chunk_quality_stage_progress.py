"""Add within-stage progress counters to chunk_quality_runs.

Revision ID: 085
Revises: 084
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '085'
down_revision: Union[str, None] = '084'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("stage_current", "stage_total")


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    for column in _COLUMNS:
        if not _has_column("chunk_quality_runs", column):
            op.add_column("chunk_quality_runs", sa.Column(column, sa.Integer(), nullable=True))


def downgrade() -> None:
    for column in _COLUMNS:
        if _has_column("chunk_quality_runs", column):
            op.drop_column("chunk_quality_runs", column)
