"""Add project_invitations table for pending invites.

Revision ID: 038
Revises: 037
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '038'
down_revision: Union[str, None] = '037'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'project_invitations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('invited_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('token', sa.String(64), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default=sa.text("'member'")),
        sa.Column(
            'allowed_sections',
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[\"observe\",\"evaluate\",\"improve\"]'::jsonb"),
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'email', name='uq_project_invitations_project_email'),
        sa.UniqueConstraint('token'),
    )
    op.create_index('ix_project_invitations_project_id', 'project_invitations', ['project_id'])
    op.create_index('ix_project_invitations_email', 'project_invitations', ['email'])


def downgrade() -> None:
    op.drop_index('ix_project_invitations_email', table_name='project_invitations')
    op.drop_index('ix_project_invitations_project_id', table_name='project_invitations')
    op.drop_table('project_invitations')
