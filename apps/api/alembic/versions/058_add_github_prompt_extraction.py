"""Add github integration type + prompt_extractions table.

Supports extracting prompts from a connected GitHub codebase: the `github`
enum value is the storage container (an auto-created Integration), and
`prompt_extractions` tracks each background extraction run's progress.

Revision ID: 058
Revises: 057
Create Date: 2026-06-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = '058'
down_revision: Union[str, None] = '057'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres can't add an enum value inside the transaction that later uses it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE integration_type ADD VALUE IF NOT EXISTS 'github'")

    # The app's startup create_all may already have materialized this table
    # (see CLAUDE.md). Only create it when missing so the migration is the
    # source of truth in production without colliding locally.
    inspector = sa.inspect(op.get_bind())
    if "prompt_extractions" in inspector.get_table_names():
        return

    op.create_table(
        "prompt_extractions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "integration_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("integrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("files_analyzed", JSONB, nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("extracted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Float(), nullable=True),
        sa.Column("num_turns", sa.Integer(), nullable=True),
        sa.Column("progress_message", sa.String(512), nullable=True),
        sa.Column("progress_log", JSONB, nullable=False, server_default="[]"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_prompt_extractions_project_id", "prompt_extractions", ["project_id"]
    )


def downgrade() -> None:
    # Note: Postgres can't drop a single enum value; the `github` value is left
    # in place. Removing it would require recreating the type.
    op.drop_index("idx_prompt_extractions_project_id", table_name="prompt_extractions")
    op.drop_table("prompt_extractions")
