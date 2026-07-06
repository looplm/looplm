"""Add min_grade to retrieval_metrics_jobs and retrieval_runs.

min_grade (1..3, default 1) is the binary-metrics strictness for the labels-path retrieval
metrics: only chunks with gold grade >= min_grade count as relevant; lower relevant grades are
treated as unjudged. Persisted on compute jobs and saved runs alongside gold_source so a run
snapshot records exactly what was measured.

Revision ID: 079
Revises: 078
Create Date: 2026-07-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '079'
down_revision: Union[str, None] = '078'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("retrieval_metrics_jobs", "retrieval_runs")


def _has_column(table: str, column: str) -> bool:
    # The app's startup create_all may already have created the column in dev (see CLAUDE.md).
    # Guard so the migration is the source of truth in prod without colliding locally.
    inspector = sa.inspect(op.get_bind())
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    for table in _TABLES:
        if _has_column(table, "min_grade"):
            continue
        op.add_column(
            table,
            sa.Column("min_grade", sa.Integer(), nullable=False, server_default=sa.text("1")),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "min_grade")
