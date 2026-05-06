"""Add feedback_suggestion_runs table to persist generated test case suggestions.

Revision ID: 041
Revises: 040
Create Date: 2026-05-06
"""
from typing import Sequence, Union

from alembic import op


revision: str = '041'
down_revision: Union[str, None] = '040'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS feedback_suggestion_runs (
            id UUID DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            error TEXT,
            feedback_type VARCHAR(16) NOT NULL DEFAULT 'all',
            filter_from_date TIMESTAMPTZ,
            filter_to_date TIMESTAMPTZ,
            filter_environment VARCHAR(255),
            filter_include_user_ids JSONB,
            filter_exclude_user_ids JSONB,
            filter_limit INTEGER NOT NULL DEFAULT 20,
            total INTEGER NOT NULL DEFAULT 0,
            processed INTEGER NOT NULL DEFAULT 0,
            suggestions JSONB NOT NULL DEFAULT '[]'::jsonb,
            count INTEGER NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # Idempotent ALTERs in case a previous create_all built the table without
    # the progress-tracking columns (dev users who restarted the API mid-design).
    op.execute("ALTER TABLE feedback_suggestion_runs ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'pending'")
    op.execute("ALTER TABLE feedback_suggestion_runs ADD COLUMN IF NOT EXISTS error TEXT")
    op.execute("ALTER TABLE feedback_suggestion_runs ADD COLUMN IF NOT EXISTS filter_limit INTEGER NOT NULL DEFAULT 20")
    op.execute("ALTER TABLE feedback_suggestion_runs ADD COLUMN IF NOT EXISTS total INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE feedback_suggestion_runs ADD COLUMN IF NOT EXISTS processed INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE feedback_suggestion_runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ")
    op.execute("ALTER TABLE feedback_suggestion_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_feedback_suggestion_runs_project_id
        ON feedback_suggestion_runs (project_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feedback_suggestion_runs")
