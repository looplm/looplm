"""Add top_questions_analyses table for LLM-based question clustering.

Revision ID: 036
Revises: 035
Create Date: 2026-03-31
"""
from typing import Sequence, Union

from alembic import op


revision: str = '036'
down_revision: Union[str, None] = '035'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS top_questions_analyses (
            id UUID DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            error TEXT,
            total_questions INTEGER NOT NULL DEFAULT 0,
            processed_questions INTEGER NOT NULL DEFAULT 0,
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
        CREATE INDEX IF NOT EXISTS idx_top_questions_analyses_project_id
        ON top_questions_analyses (project_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS top_questions_analyses")
