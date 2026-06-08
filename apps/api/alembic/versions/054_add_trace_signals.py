"""Add behavioral signal types, trace_signals table, and a classifier watermark.

Extends the ``signal_type`` enum with the four LLM-classified behavioral signals
(refusal, user_frustration, task_incomplete, loop), adds the ``trace_signals``
table that stores them per-trace, and adds ``traces.signals_classified_at`` so
the background classifier poller knows which traces it has already considered.

Note: ``ALTER TYPE ... ADD VALUE`` requires PostgreSQL 12+ to run inside a
transaction (Alembic's default). Each value is added with IF NOT EXISTS so the
migration is idempotent against the startup ``create_all``.

Revision ID: 054
Revises: 053
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = '054'
down_revision: Union[str, None] = '053'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_VALUES = ("refusal", "user_frustration", "task_incomplete", "loop")


def upgrade() -> None:
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE signal_type ADD VALUE IF NOT EXISTS '{value}'")

    op.execute(
        """
        ALTER TABLE traces ADD COLUMN IF NOT EXISTS signals_classified_at TIMESTAMPTZ
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trace_signals (
            id UUID PRIMARY KEY,
            trace_id UUID NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
            signal_type signal_type NOT NULL,
            confidence DOUBLE PRECISION CHECK (confidence >= 0 AND confidence <= 1),
            detail TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_trace_signal UNIQUE (trace_id, signal_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trace_signals_trace_id ON trace_signals (trace_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trace_signals_signal_type ON trace_signals (signal_type)"
    )
    # Partial index drives the poller's "not yet classified" scan cheaply.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_traces_unclassified
        ON traces (created_at DESC)
        WHERE signals_classified_at IS NULL
        """
    )


def downgrade() -> None:
    # Enum values cannot be dropped in PostgreSQL without recreating the type;
    # leaving the four added values in place is harmless.
    op.execute("DROP INDEX IF EXISTS idx_traces_unclassified")
    op.execute("DROP TABLE IF EXISTS trace_signals")
    op.execute("ALTER TABLE traces DROP COLUMN IF EXISTS signals_classified_at")
