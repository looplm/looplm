"""Widen eval label columns from VARCHAR to TEXT.

The eval trigger builds a job label by joining every selected dataset name with ", "
(see ``routers/eval_jobs.py``). Selecting ~20 datasets pushes that label past 255
characters, so Postgres raised StringDataRightTruncation and the request 500'd. The
same joined label is written to ``eval_runs.name`` (from the eval executors) and the
session endpoint writes a joined experiment-name label to ``eval_sessions.name``, so
all three columns are widened. Fixing only ``eval_jobs.test_suite`` would move the
failure into the background task instead of removing it.

Tests run on SQLite, which ignores VARCHAR length, so this never surfaced locally.

VARCHAR(n) -> TEXT is a metadata-only change in Postgres: no table rewrite, no
long lock.

The app's startup ``create_all`` may already have made these columns TEXT in dev
(see CLAUDE.md); each alter is guarded so it no-ops in that case.

Note: ``downgrade()`` will fail if any row already exceeds the restored limit.

Revision ID: 094
Revises: 093
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "094"
down_revision = "093"
branch_labels = None
depends_on = None


# (table, column, old VARCHAR length)
_COLUMNS = [
    ("eval_jobs", "test_suite", 255),
    ("eval_runs", "name", 512),
    ("eval_sessions", "name", 512),
]


def _current_type(inspector, table, column):
    """Return the column's type, or None if the table/column is absent."""
    if table not in inspector.get_table_names():
        return None
    for col in inspector.get_columns(table):
        if col["name"] == column:
            return col["type"]
    return None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    for table, column, old_length in _COLUMNS:
        current = _current_type(inspector, table, column)
        if current is None or isinstance(current, sa.Text):
            continue
        op.alter_column(
            table,
            column,
            existing_type=sa.String(old_length),
            type_=sa.Text(),
            existing_nullable=False,
            existing_server_default=sa.text("''") if column == "test_suite" else None,
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    for table, column, old_length in _COLUMNS:
        current = _current_type(inspector, table, column)
        if current is None:
            continue
        op.alter_column(
            table,
            column,
            existing_type=sa.Text(),
            type_=sa.String(old_length),
            existing_nullable=False,
            existing_server_default=sa.text("''") if column == "test_suite" else None,
        )
