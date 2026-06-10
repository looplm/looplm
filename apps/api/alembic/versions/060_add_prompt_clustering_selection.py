"""Add prompt clustering + extraction selection columns.

- prompts.cluster_path: ordered hierarchy a prompt belongs to (editable tree).
- prompt_extractions.planned_locations: discovered locations awaiting selection.

Revision ID: 060
Revises: 059
Create Date: 2026-06-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = '060'
down_revision: Union[str, None] = '059'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    # The app's startup create_all may already have added the column in dev
    # (see CLAUDE.md). Guard so the migration is the source of truth in prod
    # without colliding locally.
    inspector = sa.inspect(op.get_bind())
    existing = {c["name"] for c in inspector.get_columns(table)}
    if column.name not in existing:
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_missing(
        "prompts",
        sa.Column("cluster_path", JSONB, nullable=False, server_default="[]"),
    )
    _add_column_if_missing(
        "prompt_extractions",
        sa.Column("planned_locations", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("prompt_extractions", "planned_locations")
    op.drop_column("prompts", "cluster_path")
