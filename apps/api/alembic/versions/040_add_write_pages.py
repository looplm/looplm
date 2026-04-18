"""Add write_pages column for per-page write access control.

Revision ID: 040
Revises: 039
Create Date: 2026-04-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '040'
down_revision: Union[str, None] = '039'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'project_members',
        sa.Column('write_pages', postgresql.JSONB(), nullable=True, server_default=sa.text('null')),
    )
    op.add_column(
        'project_invitations',
        sa.Column('write_pages', postgresql.JSONB(), nullable=True, server_default=sa.text('null')),
    )


def downgrade() -> None:
    op.drop_column('project_invitations', 'write_pages')
    op.drop_column('project_members', 'write_pages')
