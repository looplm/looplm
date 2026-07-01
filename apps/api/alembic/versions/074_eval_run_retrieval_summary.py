"""Persist a per-run retrieval-metrics snapshot.

Adds a nullable ``retrieval_summary`` JSONB column to eval_runs. The eval executor computes the
URLs-path retrieval metrics (recall@k, nDCG@k, MRR, hit-rate@k, precision@k) at completion and
stores them here, so each run carries its retrieval quality without an on-demand recompute.

Revision ID: 074
Revises: 073
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = '074'
down_revision: Union[str, None] = '073'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "eval_runs" not in sa.inspect(op.get_bind()).get_table_names():
        return
    if "retrieval_summary" not in _columns("eval_runs"):
        op.add_column(
            "eval_runs",
            sa.Column("retrieval_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )


def downgrade() -> None:
    if "retrieval_summary" in _columns("eval_runs"):
        op.drop_column("eval_runs", "retrieval_summary")
