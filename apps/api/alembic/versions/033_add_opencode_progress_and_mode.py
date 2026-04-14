"""Add progress tracking and mode columns to opencode_analyses.

Revision ID: 033
Revises: 032
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = '033'
down_revision: Union[str, None] = '032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'opencode_analyses',
        sa.Column('analysis_mode', sa.String(32), nullable=True, server_default=sa.text("'detailed'")),
    )
    op.add_column(
        'opencode_analyses',
        sa.Column('progress_message', sa.String(512), nullable=True),
    )
    op.add_column(
        'opencode_analyses',
        sa.Column('progress_log', JSONB, nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column('opencode_analyses', 'progress_log')
    op.drop_column('opencode_analyses', 'progress_message')
    op.drop_column('opencode_analyses', 'analysis_mode')
