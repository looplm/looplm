"""Add chunk_relevance_labels (human chunk-level retrieval relevance judgments).

Revision ID: 065
Revises: 064
Create Date: 2026-06-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = '065'
down_revision: Union[str, None] = '064'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    # Guard against reruns in dev (startup create_all may have already made the table).
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _has_table("chunk_relevance_labels"):
        return
    op.create_table(
        "chunk_relevance_labels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("test_id", sa.String(512), nullable=False),
        sa.Column("chunk_id", sa.String(512), nullable=False),
        sa.Column("relevant", sa.Boolean(), nullable=False),
        sa.Column("content_preview", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "labeled_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("project_id", "test_id", "chunk_id", name="uq_chunk_label_project_test_chunk"),
    )
    op.create_index("ix_chunk_relevance_labels_project_id", "chunk_relevance_labels", ["project_id"])
    op.create_index("idx_chunk_labels_project_test", "chunk_relevance_labels", ["project_id", "test_id"])


def downgrade() -> None:
    op.drop_index("idx_chunk_labels_project_test", table_name="chunk_relevance_labels")
    op.drop_index("ix_chunk_relevance_labels_project_id", table_name="chunk_relevance_labels")
    op.drop_table("chunk_relevance_labels")
