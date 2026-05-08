"""Add sync_phase, sync_message, sync_since columns to integrations.

Revision ID: 042
Revises: 041
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = '042'
down_revision: Union[str, None] = '041'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE integrations ADD COLUMN IF NOT EXISTS sync_phase VARCHAR(32)")
    op.execute("ALTER TABLE integrations ADD COLUMN IF NOT EXISTS sync_message VARCHAR(255)")
    op.execute("ALTER TABLE integrations ADD COLUMN IF NOT EXISTS sync_since TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE integrations DROP COLUMN IF EXISTS sync_since")
    op.execute("ALTER TABLE integrations DROP COLUMN IF EXISTS sync_message")
    op.execute("ALTER TABLE integrations DROP COLUMN IF EXISTS sync_phase")
