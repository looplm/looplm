"""Per-annotator chunk labels + gold-label adjudication.

Widens the chunk_relevance_labels unique key to include labeled_by (so multiple annotators
can judge the same chunk, enabling inter-annotator agreement), and adds chunk_gold_labels for
adjudicated verdicts that override the majority vote.

Revision ID: 068
Revises: 067
Create Date: 2026-06-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = '068'
down_revision: Union[str, None] = '067'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_UQ = "uq_chunk_label_project_test_chunk"
_NEW_UQ = "uq_chunk_label_project_test_chunk_user"


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _constraint_names(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_unique_constraints(table)}


def upgrade() -> None:
    if _has_table("chunk_relevance_labels"):
        existing = _constraint_names("chunk_relevance_labels")
        if _OLD_UQ in existing:
            op.drop_constraint(_OLD_UQ, "chunk_relevance_labels", type_="unique")
        if _NEW_UQ not in existing:
            op.create_unique_constraint(
                _NEW_UQ,
                "chunk_relevance_labels",
                ["project_id", "test_id", "chunk_id", "labeled_by"],
            )

    if not _has_table("chunk_gold_labels"):
        op.create_table(
            "chunk_gold_labels",
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
            sa.Column(
                "decided_by",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("project_id", "test_id", "chunk_id", name="uq_chunk_gold_project_test_chunk"),
        )
        op.create_index("ix_chunk_gold_labels_project_id", "chunk_gold_labels", ["project_id"])
        op.create_index("idx_chunk_gold_project_test", "chunk_gold_labels", ["project_id", "test_id"])


def downgrade() -> None:
    if _has_table("chunk_gold_labels"):
        op.drop_index("idx_chunk_gold_project_test", table_name="chunk_gold_labels")
        op.drop_index("ix_chunk_gold_labels_project_id", table_name="chunk_gold_labels")
        op.drop_table("chunk_gold_labels")

    if _has_table("chunk_relevance_labels"):
        existing = _constraint_names("chunk_relevance_labels")
        if _NEW_UQ in existing:
            op.drop_constraint(_NEW_UQ, "chunk_relevance_labels", type_="unique")
        if _OLD_UQ not in existing:
            op.create_unique_constraint(
                _OLD_UQ, "chunk_relevance_labels", ["project_id", "test_id", "chunk_id"]
            )
