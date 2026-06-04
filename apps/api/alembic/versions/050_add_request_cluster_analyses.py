"""Add request_cluster_analyses table for request-type clustering analytics.

Stores LLM-clustered user-request themes plus per-theme outcome cross-tabs that
drive the Analytics page's request-type × outcome heatmap. Mirrors the existing
top_questions_analyses table but is scoped to all traffic, not just feedback.

Revision ID: 050
Revises: 049
Create Date: 2026-06-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = '050'
down_revision: Union[str, None] = '049'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'request_cluster_analyses',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('total_requests', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('processed_requests', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('results', postgresql.JSONB(), nullable=True),
        sa.Column('filter_from_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('filter_to_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('filter_environment', sa.String(255), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_request_cluster_analyses_project_id', 'request_cluster_analyses', ['project_id'])


def downgrade() -> None:
    op.drop_index('idx_request_cluster_analyses_project_id', table_name='request_cluster_analyses')
    op.drop_table('request_cluster_analyses')
