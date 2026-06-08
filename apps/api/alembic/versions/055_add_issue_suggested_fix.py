"""Add issues.suggested_fix, populated by the diagnosis step alongside root_cause.

Revision ID: 055
Revises: 054
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = '055'
down_revision: Union[str, None] = '054'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE issues ADD COLUMN IF NOT EXISTS suggested_fix TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE issues DROP COLUMN IF EXISTS suggested_fix")
