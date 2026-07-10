"""Add stage column to chunk_quality_runs (live progress step).

Revision ID: 084
Revises: 083
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '084'
down_revision: Union[str, None] = '083'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column("chunk_quality_runs", "stage"):
        op.add_column("chunk_quality_runs", sa.Column("stage", sa.String(length=64), nullable=True))


def downgrade() -> None:
    if _has_column("chunk_quality_runs", "stage"):
        op.drop_column("chunk_quality_runs", "stage")
