"""Add passage_relevance_labels (per-passage relevance selections, additive to chunk labeling).

A passage selection is a finer-grained refinement hanging off a chunk label: within a chunk
judged relevant, an annotator marks which sentence-level passages actually help answer the
query. One row per ``(project, test_id, chunk_id, passage_id, annotator)``. The chunk-level
label tables are untouched.

The app's startup ``create_all`` may already have made this table in dev (see CLAUDE.md); this
revision exists so production upgrades create it explicitly.

Revision ID: 086
Revises: 085
Create Date: 2026-07-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = '086'
down_revision: Union[str, None] = '085'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("passage_relevance_labels"):
        return
    op.create_table(
        "passage_relevance_labels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("test_id", sa.String(length=512), nullable=False),
        sa.Column("chunk_id", sa.String(length=512), nullable=False),
        sa.Column("passage_id", sa.String(length=512), nullable=False),
        sa.Column("relevant", sa.Integer(), nullable=False),
        sa.Column(
            "passage_source",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'chunk_split'"),
        ),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("text_preview", sa.Text(), nullable=True),
        sa.Column("annotator", sa.String(length=64), nullable=True),
        sa.Column(
            "labeled_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "project_id",
            "test_id",
            "chunk_id",
            "passage_id",
            "labeled_by",
            name="uq_passage_label_project_test_chunk_passage_user",
        ),
    )
    op.create_index(
        "idx_passage_labels_project_test_chunk",
        "passage_relevance_labels",
        ["project_id", "test_id", "chunk_id"],
    )
    op.create_index(
        "ix_passage_relevance_labels_project_id",
        "passage_relevance_labels",
        ["project_id"],
    )


def downgrade() -> None:
    if not _has_table("passage_relevance_labels"):
        return
    op.drop_index(
        "ix_passage_relevance_labels_project_id", table_name="passage_relevance_labels"
    )
    op.drop_index(
        "idx_passage_labels_project_test_chunk", table_name="passage_relevance_labels"
    )
    op.drop_table("passage_relevance_labels")
