"""Add experiments and eval_sessions tables, link to eval_runs.

Revision ID: 032
Revises: 031
Create Date: 2026-03-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = '032'
down_revision: Union[str, None] = '031'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- experiments table ---
    op.create_table(
        'experiments',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('variables', JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('project_id', 'name'),
    )
    op.create_index('idx_experiments_project_id', 'experiments', ['project_id'])

    # --- eval_sessions table ---
    op.create_table(
        'eval_sessions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(512), nullable=False),
        sa.Column('status', sa.Enum('pending', 'running', 'completed', 'failed', 'cancelled', name='eval_job_status', create_type=False), nullable=False, server_default=sa.text("'pending'")),
        sa.Column('dataset_ids', JSONB(), nullable=True),
        sa.Column('experiment_ids', JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('config', JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('progress_current', sa.Integer(), nullable=True),
        sa.Column('progress_total', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_eval_sessions_project_id', 'eval_sessions', ['project_id'])
    op.create_index('idx_eval_sessions_started_at', 'eval_sessions', [sa.text('started_at DESC')])

    # --- Add session_id and experiment_id to eval_runs ---
    op.add_column('eval_runs', sa.Column('session_id', UUID(as_uuid=True), nullable=True))
    op.add_column('eval_runs', sa.Column('experiment_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_eval_runs_session_id', 'eval_runs', 'eval_sessions',
        ['session_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_eval_runs_experiment_id', 'eval_runs', 'experiments',
        ['experiment_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('idx_eval_runs_session_id', 'eval_runs', ['session_id'])


def downgrade() -> None:
    op.drop_index('idx_eval_runs_session_id', table_name='eval_runs')
    op.drop_constraint('fk_eval_runs_experiment_id', 'eval_runs', type_='foreignkey')
    op.drop_constraint('fk_eval_runs_session_id', 'eval_runs', type_='foreignkey')
    op.drop_column('eval_runs', 'experiment_id')
    op.drop_column('eval_runs', 'session_id')
    op.drop_index('idx_eval_sessions_started_at', table_name='eval_sessions')
    op.drop_index('idx_eval_sessions_project_id', table_name='eval_sessions')
    op.drop_table('eval_sessions')
    op.drop_index('idx_experiments_project_id', table_name='experiments')
    op.drop_table('experiments')
