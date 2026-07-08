"""Add failure_mode_analyses table.

Backs the Feedback → Failure Modes feature: each row is one background job that
diagnoses a set of negative-feedback traces into root-cause categories and clusters
them into named failure modes (stored in ``results`` JSONB). Mirrors the shape of
``feedback_theme_analyses``.

Revision ID: 081
Revises: 080
Create Date: 2026-07-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = '081'
down_revision: Union[str, None] = '080'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    # The app's startup create_all may already have created the table in dev (see CLAUDE.md).
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names()


def _has_index(table: str, index: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return index in {i["name"] for i in inspector.get_indexes(table)}


def upgrade() -> None:
    if not _has_table("failure_mode_analyses"):
        op.create_table(
            "failure_mode_analyses",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "project_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("total_traces", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("processed_traces", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("results", JSONB(), nullable=True),
            sa.Column("category_counts", JSONB(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("filter_from_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("filter_to_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("filter_environment", sa.String(length=255), nullable=True),
            sa.Column("filter_selected_feedback_ids", JSONB(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )

    if not _has_index("failure_mode_analyses", "idx_failure_mode_analyses_project_id"):
        op.create_index(
            "idx_failure_mode_analyses_project_id",
            "failure_mode_analyses",
            ["project_id"],
        )


def downgrade() -> None:
    if _has_index("failure_mode_analyses", "idx_failure_mode_analyses_project_id"):
        op.drop_index("idx_failure_mode_analyses_project_id", table_name="failure_mode_analyses")
    if _has_table("failure_mode_analyses"):
        op.drop_table("failure_mode_analyses")
