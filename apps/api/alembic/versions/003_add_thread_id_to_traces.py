"""Add thread_id column to traces.

Revision ID: 003_add_thread_id_to_traces
Revises: 002_add_sync_progress_fields
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa

revision = "003_add_thread_id_to_traces"
down_revision = "002_add_sync_progress_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("traces", sa.Column("thread_id", sa.String(512), nullable=True))

    # Partial index on thread_id (only non-NULL rows)
    op.create_index(
        "idx_traces_thread_id",
        "traces",
        ["thread_id"],
        postgresql_where=sa.text("thread_id IS NOT NULL"),
    )

    # Composite index for filtering by integration + thread
    op.create_index(
        "idx_traces_integration_thread_id",
        "traces",
        ["integration_id", "thread_id"],
    )

    # Backfill from JSONB metadata
    op.execute(
        """
        UPDATE traces
        SET thread_id = COALESCE(
            metadata->>'thread_id',
            metadata->>'session_id',
            metadata->>'conversation_id'
        )
        WHERE metadata->>'thread_id' IS NOT NULL
           OR metadata->>'session_id' IS NOT NULL
           OR metadata->>'conversation_id' IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("idx_traces_integration_thread_id", table_name="traces")
    op.drop_index("idx_traces_thread_id", table_name="traces")
    op.drop_column("traces", "thread_id")
