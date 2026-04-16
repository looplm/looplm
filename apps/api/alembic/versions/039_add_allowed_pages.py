"""Add allowed_pages column for page-level access control.

Revision ID: 039
Revises: 038
Create Date: 2026-04-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '039'
down_revision: Union[str, None] = '038'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'project_members',
        sa.Column('allowed_pages', postgresql.JSONB(), nullable=True, server_default=sa.text('null')),
    )
    op.add_column(
        'project_invitations',
        sa.Column('allowed_pages', postgresql.JSONB(), nullable=True, server_default=sa.text('null')),
    )


def downgrade() -> None:
    op.drop_column('project_invitations', 'allowed_pages')
    op.drop_column('project_members', 'allowed_pages')
