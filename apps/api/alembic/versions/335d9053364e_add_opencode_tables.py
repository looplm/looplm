"""add_opencode_tables

Revision ID: 335d9053364e
Revises: 026
Create Date: 2026-03-24 17:41:38.394047
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '335d9053364e'
down_revision: Union[str, None] = '026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'opencode_analyses',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('eval_run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('files_analyzed', postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column('failure_summary', sa.Text(), nullable=True),
        sa.Column('suggestion_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('total_cost_usd', sa.Float(), nullable=True),
        sa.Column('num_turns', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['eval_run_id'], ['eval_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_opencode_analyses_project_id', 'opencode_analyses', ['project_id'])
    op.create_index('idx_opencode_analyses_eval_run_id', 'opencode_analyses', ['eval_run_id'])

    op.create_table(
        'code_suggestions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('analysis_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('type', sa.Enum('prompt_change', 'code_fix', 'config_change', 'architecture_change', name='code_suggestion_type'), nullable=False),
        sa.Column('title', sa.String(512), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('file_path', sa.String(1024), nullable=True),
        sa.Column('line_start', sa.Integer(), nullable=True),
        sa.Column('line_end', sa.Integer(), nullable=True),
        sa.Column('diff', postgresql.JSONB(), nullable=True),
        sa.Column('impact', sa.String(32), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('reasoning', sa.Text(), nullable=True),
        sa.Column('related_test_ids', postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column('status', sa.Enum('pending', 'applied', 'dismissed', name='code_suggestion_status'), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['opencode_analyses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_code_suggestions_analysis_id', 'code_suggestions', ['analysis_id'])
    op.create_index('idx_code_suggestions_project_id', 'code_suggestions', ['project_id'])
    op.create_index('idx_code_suggestions_status', 'code_suggestions', ['status'])


def downgrade() -> None:
    op.drop_index('idx_code_suggestions_status', table_name='code_suggestions')
    op.drop_index('idx_code_suggestions_project_id', table_name='code_suggestions')
    op.drop_index('idx_code_suggestions_analysis_id', table_name='code_suggestions')
    op.drop_table('code_suggestions')
    op.drop_index('idx_opencode_analyses_eval_run_id', table_name='opencode_analyses')
    op.drop_index('idx_opencode_analyses_project_id', table_name='opencode_analyses')
    op.drop_table('opencode_analyses')
    op.execute("DROP TYPE IF EXISTS code_suggestion_type")
    op.execute("DROP TYPE IF EXISTS code_suggestion_status")
