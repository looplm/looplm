"""add_feedback_evaluation_tables

Revision ID: 027
Revises: 335d9053364e
Create Date: 2026-03-26
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '027'
down_revision: Union[str, None] = '335d9053364e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'feedback_evaluations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('total_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('evaluated_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('suspicious_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('helpful_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('unhelpful_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_feedback_evaluations_project_id', 'feedback_evaluations', ['project_id'])

    op.create_table(
        'feedback_eval_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('evaluation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('feedback_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('trace_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('score_name', sa.String(128), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('trace_input_preview', sa.Text(), nullable=True),
        sa.Column('verdict', sa.String(32), nullable=False),
        sa.Column('reasoning', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['evaluation_id'], ['feedback_evaluations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_feedback_eval_results_evaluation_id', 'feedback_eval_results', ['evaluation_id'])


def downgrade() -> None:
    op.drop_index('idx_feedback_eval_results_evaluation_id', table_name='feedback_eval_results')
    op.drop_table('feedback_eval_results')
    op.drop_index('idx_feedback_evaluations_project_id', table_name='feedback_evaluations')
    op.drop_table('feedback_evaluations')
