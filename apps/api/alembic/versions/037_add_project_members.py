"""Add project_members table for role-based section access control.

Revision ID: 037
Revises: 036
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '037'
down_revision: Union[str, None] = '036'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'project_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default=sa.text("'member'")),
        sa.Column(
            'allowed_sections',
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[\"observe\",\"evaluate\",\"improve\"]'::jsonb"),
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'user_id', name='uq_project_members_project_user'),
    )
    op.create_index('ix_project_members_project_id', 'project_members', ['project_id'])
    op.create_index('ix_project_members_user_id', 'project_members', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_project_members_user_id', table_name='project_members')
    op.drop_index('ix_project_members_project_id', table_name='project_members')
    op.drop_table('project_members')
