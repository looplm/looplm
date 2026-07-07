"""Add execution_status to eval_results.

execution_status ('ok' | 'degraded' | 'error') records whether a result ran against a
representative target path. 'degraded' = the target fell back to keyword-only retrieval
(embeddings throttled); 'error' = the call failed after retries. Non-'ok' rows are the
dead-letter queue and are excluded from a run's headline pass rate. Mirrors
metadata['execution']['status']; backfilled from that key for existing rows.

Revision ID: 080
Revises: 079
Create Date: 2026-07-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '080'
down_revision: Union[str, None] = '079'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    # The app's startup create_all may already have added the column in dev (see CLAUDE.md).
    inspector = sa.inspect(op.get_bind())
    return column in {c["name"] for c in inspector.get_columns(table)}


def _has_index(table: str, index: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return index in {i["name"] for i in inspector.get_indexes(table)}


def upgrade() -> None:
    if not _has_column("eval_results", "execution_status"):
        op.add_column(
            "eval_results",
            sa.Column(
                "execution_status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'ok'"),
            ),
        )
        # Backfill from the JSON metadata written before the column existed.
        op.execute(
            """
            UPDATE eval_results
            SET execution_status = COALESCE(metadata #>> '{execution,status}', 'ok')
            WHERE metadata #>> '{execution,status}' IS NOT NULL
            """
        )

    if not _has_index("eval_results", "idx_eval_results_run_execution"):
        op.create_index(
            "idx_eval_results_run_execution",
            "eval_results",
            ["run_id", "execution_status"],
        )


def downgrade() -> None:
    if _has_index("eval_results", "idx_eval_results_run_execution"):
        op.drop_index("idx_eval_results_run_execution", table_name="eval_results")
    if _has_column("eval_results", "execution_status"):
        op.drop_column("eval_results", "execution_status")
