"""Add source_expectations + source_gap_runs (wanted-status source registry).

Revision ID: 061
Revises: 060
Create Date: 2026-06-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = '061'
down_revision: Union[str, None] = '060'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    # The app's startup create_all may already have created the table in dev
    # (see CLAUDE.md). Guard so the migration is the source of truth in prod
    # without colliding locally.
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("source_expectations"):
        op.create_table(
            "source_expectations",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "project_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "provider_id",
                UUID(as_uuid=True),
                sa.ForeignKey("index_providers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(512), nullable=False),
            sa.Column("html_url", sa.String(2048), nullable=True),
            sa.Column("pdf_url", sa.String(2048), nullable=True),
            sa.Column("adapter_tag", sa.String(64), nullable=True),
            sa.Column("typ", sa.String(255), nullable=True),
            sa.Column("sparte", sa.String(255), nullable=True),
            sa.Column("thema", sa.String(255), nullable=True),
            sa.Column("publisher", sa.String(255), nullable=True),
            sa.Column("hierarchie", sa.String(512), nullable=True),
            sa.Column("update_frequency", sa.String(255), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("ack_note", sa.Text(), nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "project_id", "provider_id", "name", name="uq_source_expectation_name"
            ),
        )
        op.create_index(
            "idx_source_expectations_lookup",
            "source_expectations",
            ["project_id", "provider_id"],
        )

    if not _has_table("source_gap_runs"):
        op.create_table(
            "source_gap_runs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "project_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "provider_id",
                UUID(as_uuid=True),
                sa.ForeignKey("index_providers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("total", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("results", JSONB(), nullable=True),
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
            "idx_source_gap_runs_lookup", "source_gap_runs", ["project_id", "provider_id"]
        )


def downgrade() -> None:
    op.drop_table("source_gap_runs")
    op.drop_table("source_expectations")
