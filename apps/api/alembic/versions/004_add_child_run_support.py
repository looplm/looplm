"""Add child run support to traces (parent_trace_id, root_trace_id, run_type).

Revision ID: 004_add_child_run_support
Revises: 003_add_thread_id_to_traces
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "004_add_child_run_support"
down_revision = "003_add_thread_id_to_traces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "traces",
        sa.Column("parent_trace_id", UUID(as_uuid=True), sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=True),
    )
    op.add_column(
        "traces",
        sa.Column("root_trace_id", UUID(as_uuid=True), sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=True),
    )
    op.add_column(
        "traces",
        sa.Column("run_type", sa.String(64), nullable=True),
    )

    op.create_index("idx_traces_parent_trace_id", "traces", ["parent_trace_id"])
    op.create_index("idx_traces_root_trace_id", "traces", ["root_trace_id"])


def downgrade() -> None:
    op.drop_index("idx_traces_root_trace_id", table_name="traces")
    op.drop_index("idx_traces_parent_trace_id", table_name="traces")
    op.drop_column("traces", "run_type")
    op.drop_column("traces", "root_trace_id")
    op.drop_column("traces", "parent_trace_id")
