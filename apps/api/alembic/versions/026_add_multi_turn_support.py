"""add_multi_turn_support

Revision ID: 026
Revises: cfb50dd8225a
Create Date: 2026-03-24 09:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '026'
down_revision: Union[str, None] = 'cfb50dd8225a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('test_cases', sa.Column('follow_up_prompts', postgresql.JSONB(), nullable=True))
    op.add_column('eval_results', sa.Column('turns_to_pass', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('eval_results', 'turns_to_pass')
    op.drop_column('test_cases', 'follow_up_prompts')
