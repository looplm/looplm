"""Add auto-sync schedule columns to integrations.

Lets users schedule recurring trace syncs per (pull-based) integration.
auto_sync_interval_minutes NULL = disabled; next_sync_at is the durable due marker.

Revision ID: 051
Revises: 050
Create Date: 2026-06-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '051'
down_revision: Union[str, None] = '050'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'integrations',
        sa.Column('auto_sync_interval_minutes', sa.Integer(), nullable=True),
    )
    op.add_column(
        'integrations',
        sa.Column('next_sync_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('integrations', 'next_sync_at')
    op.drop_column('integrations', 'auto_sync_interval_minutes')
