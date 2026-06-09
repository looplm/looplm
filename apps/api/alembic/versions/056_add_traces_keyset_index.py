"""Add composite index for keyset pagination of the traces list.

Backs the (integration_id, start_time DESC, id DESC) cursor used by the trace
list endpoint. Built CONCURRENTLY so it doesn't lock writes on a large traces
table — hence the autocommit block (CREATE INDEX CONCURRENTLY cannot run inside
a transaction).

Revision ID: 056
Revises: 055
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op


revision: str = '056'
down_revision: Union[str, None] = '055'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_traces_integration_start_time_id "
            "ON traces (integration_id, start_time DESC, id DESC)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_traces_integration_start_time_id")
