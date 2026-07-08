"""Add source scan tables (bulk completeness scan for Data Sources 'Source review').

``source_scan_runs`` tracks a background scan job (status + progress); each source's
verdict is upserted into ``source_scan_results`` (one row per expectation, latest
wins). Rows with execution_status='error' are the dead-letter set surfaced for retry.

Revision ID: 082
Revises: 081
Create Date: 2026-07-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = '082'
down_revision: Union[str, None] = '081'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    # The app's startup create_all may already have made these in dev (see CLAUDE.md).
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table("source_scan_runs"):
        op.create_table(
            "source_scan_runs",
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
            sa.Column("scope", sa.String(length=16), nullable=False, server_default=sa.text("'all'")),
            sa.Column(
                "status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")
            ),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("total", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
            "idx_source_scan_runs_lookup", "source_scan_runs", ["project_id", "provider_id"]
        )

    if not _has_table("source_scan_results"):
        op.create_table(
            "source_scan_results",
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
            sa.Column(
                "expectation_id",
                UUID(as_uuid=True),
                sa.ForeignKey("source_expectations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "resolution", sa.String(length=16), nullable=False, server_default=sa.text("'none'")
            ),
            sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("kind", sa.String(length=32), nullable=True),
            sa.Column("matched_url", sa.String(length=2048), nullable=True),
            sa.Column("matched_title", sa.String(length=512), nullable=True),
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "missing_chunk_count", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column(
                "ordinal_checked", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column(
                "execution_status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'ok'"),
            ),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column(
                "scanned_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "project_id", "provider_id", "expectation_id", name="uq_source_scan_result"
            ),
        )
        op.create_index(
            "idx_source_scan_results_dlq",
            "source_scan_results",
            ["project_id", "provider_id", "execution_status"],
        )


def downgrade() -> None:
    if _has_table("source_scan_results"):
        op.drop_index("idx_source_scan_results_dlq", table_name="source_scan_results")
        op.drop_table("source_scan_results")
    if _has_table("source_scan_runs"):
        op.drop_index("idx_source_scan_runs_lookup", table_name="source_scan_runs")
        op.drop_table("source_scan_runs")
