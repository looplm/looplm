"""Add passage_offset_backfill_runs (background job that anchors passage labels to doc offsets).

One row per launch of the passage document-offset backfill, driven pending → running →
completed/failed so the labeling UI can trigger it and poll per-outcome tallies. See
``app.services.passage_offset_backfill``.

The app's startup ``create_all`` may already have made this table in dev (see CLAUDE.md); this
revision exists so production upgrades create it explicitly.

Revision ID: 088
Revises: 087
Create Date: 2026-07-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = '088'
down_revision: Union[str, None] = '087'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "passage_offset_backfill_runs"


def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names()


def upgrade() -> None:
    if _has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("total_chunks", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("processed_chunks", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("anchored", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("no_offset", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("chunk_missing", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("no_split_match", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("drifted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("idx_passage_offset_backfill_project", _TABLE, ["project_id"])


def downgrade() -> None:
    if not _has_table(_TABLE):
        return
    op.drop_index("idx_passage_offset_backfill_project", table_name=_TABLE)
    op.drop_table(_TABLE)
