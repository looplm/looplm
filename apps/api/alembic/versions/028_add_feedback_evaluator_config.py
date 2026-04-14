"""add_feedback_evaluator_config

Revision ID: 028
Revises: 027
Create Date: 2026-03-26
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '028'
down_revision: Union[str, None] = '027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create feedback_evaluator_configs table
    op.create_table(
        'feedback_evaluator_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('verdicts', postgresql.JSONB(), server_default=sa.text("'[\"suspicious\", \"helpful\", \"unhelpful\"]'"), nullable=False),
        sa.Column('default_verdict', sa.String(32), server_default=sa.text("'unhelpful'"), nullable=False),
        sa.Column('model', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', name='uq_feedback_evaluator_config_project'),
    )

    # Add verdict_counts JSONB column to feedback_evaluations
    op.add_column(
        'feedback_evaluations',
        sa.Column('verdict_counts', postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
    )

    # Backfill verdict_counts from legacy columns
    op.execute("""
        UPDATE feedback_evaluations SET verdict_counts = jsonb_build_object(
            'suspicious', suspicious_count,
            'helpful', helpful_count,
            'unhelpful', unhelpful_count
        )
    """)


def downgrade() -> None:
    op.drop_column('feedback_evaluations', 'verdict_counts')
    op.drop_table('feedback_evaluator_configs')
