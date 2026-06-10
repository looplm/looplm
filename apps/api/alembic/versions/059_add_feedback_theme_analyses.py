"""Add feedback_theme_analyses table for LLM-based feedback comment clustering.

Revision ID: 059
Revises: 058
Create Date: 2026-06-10
"""
from typing import Sequence, Union

from alembic import op


revision: str = '059'
down_revision: Union[str, None] = '058'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS feedback_theme_analyses (
            id UUID DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            error TEXT,
            total_comments INTEGER NOT NULL DEFAULT 0,
            processed_comments INTEGER NOT NULL DEFAULT 0,
            results JSONB,
            filter_from_date TIMESTAMPTZ,
            filter_to_date TIMESTAMPTZ,
            filter_environment VARCHAR(255),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_feedback_theme_analyses_project_id
        ON feedback_theme_analyses (project_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feedback_theme_analyses")
