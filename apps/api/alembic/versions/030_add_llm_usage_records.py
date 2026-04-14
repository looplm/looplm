"""Add llm_usage_records table for cost tracking.

Revision ID: 030
Revises: 029
Create Date: 2026-03-26
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '030'
down_revision: Union[str, None] = '029'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'llm_usage_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('service_name', sa.String(128), nullable=False),
        sa.Column('function_name', sa.String(128), nullable=False),
        sa.Column('provider', sa.String(32), nullable=False),
        sa.Column('model', sa.String(128), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('total_tokens', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('cached_tokens', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('reasoning_tokens', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('request_metadata', postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_llm_usage_project_id', 'llm_usage_records', ['project_id'])
    op.create_index('idx_llm_usage_created_at', 'llm_usage_records', [sa.text('created_at DESC')])
    op.create_index('idx_llm_usage_service_name', 'llm_usage_records', ['service_name'])
    op.create_index('idx_llm_usage_project_service', 'llm_usage_records', ['project_id', 'service_name'])
    op.create_index('idx_llm_usage_project_created', 'llm_usage_records', ['project_id', sa.text('created_at DESC')])


def downgrade() -> None:
    op.drop_index('idx_llm_usage_project_created', table_name='llm_usage_records')
    op.drop_index('idx_llm_usage_project_service', table_name='llm_usage_records')
    op.drop_index('idx_llm_usage_service_name', table_name='llm_usage_records')
    op.drop_index('idx_llm_usage_created_at', table_name='llm_usage_records')
    op.drop_index('idx_llm_usage_project_id', table_name='llm_usage_records')
    op.drop_table('llm_usage_records')
