"""Add config column to chunk_quality_runs (extended-pass toggles and caps).

Revision ID: 083
Revises: 082
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = '083'
down_revision: Union[str, None] = '082'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    # The app's startup create_all may already have added this in dev (see CLAUDE.md).
    inspector = sa.inspect(op.get_bind())
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column("chunk_quality_runs", "config"):
        op.add_column("chunk_quality_runs", sa.Column("config", JSONB, nullable=True))


def downgrade() -> None:
    if _has_column("chunk_quality_runs", "config"):
        op.drop_column("chunk_quality_runs", "config")
