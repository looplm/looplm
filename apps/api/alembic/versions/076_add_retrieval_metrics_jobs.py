"""Add retrieval_metrics_jobs (detached compute jobs for labels-path metrics).

Backs the panel's fire-and-poll Compute: a row per computation carrying settings (view, gold source,
datasets), status, progress, and — on failure — the error message + traceback. The result itself is
written to the Redis metrics cache, not here.

Revision ID: 076
Revises: 075
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = '076'
down_revision: Union[str, None] = '075'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    # The app's startup create_all may already have created the table in dev
    # (see CLAUDE.md). Guard so the migration is the source of truth in prod
    # without colliding locally.
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table("retrieval_metrics_jobs"):
        return
    op.create_table(
        "retrieval_metrics_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("view", sa.String(16), nullable=False, server_default=sa.text("'overall'")),
        sa.Column("gold_source", sa.String(16), nullable=False, server_default=sa.text("'human'")),
        sa.Column("dataset_ids", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trace", sa.Text(), nullable=True),
        sa.Column("progress_current", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_retrieval_metrics_jobs_project_created",
        "retrieval_metrics_jobs",
        ["project_id", "started_at"],
    )
    op.create_index(
        "idx_retrieval_metrics_jobs_status", "retrieval_metrics_jobs", ["status"]
    )


def downgrade() -> None:
    op.drop_table("retrieval_metrics_jobs")
