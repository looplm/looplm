"""Add retrieval_runs (durable labels-path retrieval-metric snapshots).

Persists each labels-path retrieval-quality computation as an annotatable, comparable run: the
settings snapshot (datasets + gold source + ks), the metric blobs (overall + optional by-stage),
and editable metadata (name, pipeline version, index name/version, notes).

Revision ID: 075
Revises: 074
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = '075'
down_revision: Union[str, None] = '074'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    # The app's startup create_all may already have created the table in dev
    # (see CLAUDE.md). Guard so the migration is the source of truth in prod
    # without colliding locally.
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table("retrieval_runs"):
        return
    op.create_table(
        "retrieval_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("gold_source", sa.String(16), nullable=False, server_default=sa.text("'human'")),
        sa.Column("dataset_ids", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("dataset_names", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("ks", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("metrics", JSONB(), nullable=False),
        sa.Column("by_stage", JSONB(), nullable=True),
        sa.Column("total_cases", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("evaluated_cases", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("pipeline_version", sa.String(255), nullable=True),
        sa.Column("index_name", sa.String(255), nullable=True),
        sa.Column("index_version", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_retrieval_runs_project_created", "retrieval_runs", ["project_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("retrieval_runs")
