"""Add async run/progress fields to advisor_analyses.

The architecture advisor gains an optional repo-aware agentic path that runs as
a background task. This adds the lifecycle/progress columns it needs (mirroring
opencode_analyses) plus a project_id for repo resolution and cost attribution.
All columns are nullable / server-defaulted so existing synchronous graph-only
rows remain valid and read back as completed.

Revision ID: 047
Revises: 046
Create Date: 2026-06-03
"""
from typing import Sequence, Union

from alembic import op


revision: str = '047'
down_revision: Union[str, None] = '046'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Columns may already exist from startup create_all on a running instance,
    # so guard each add (ADD COLUMN IF NOT EXISTS).
    op.execute(
        """
        ALTER TABLE advisor_analyses
            ADD COLUMN IF NOT EXISTS project_id UUID
                REFERENCES projects(id) ON DELETE CASCADE,
            ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'completed',
            ADD COLUMN IF NOT EXISTS error TEXT,
            ADD COLUMN IF NOT EXISTS progress_message VARCHAR(512),
            ADD COLUMN IF NOT EXISTS progress_log JSONB NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS files_analyzed JSONB NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS num_turns INTEGER,
            ADD COLUMN IF NOT EXISTS total_cost_usd DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS repo_used BOOLEAN NOT NULL DEFAULT false;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_advisor_analyses_project_id "
        "ON advisor_analyses (project_id);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_advisor_analyses_project_id;")
    op.execute(
        """
        ALTER TABLE advisor_analyses
            DROP COLUMN IF EXISTS project_id,
            DROP COLUMN IF EXISTS status,
            DROP COLUMN IF EXISTS error,
            DROP COLUMN IF EXISTS progress_message,
            DROP COLUMN IF EXISTS progress_log,
            DROP COLUMN IF EXISTS files_analyzed,
            DROP COLUMN IF EXISTS started_at,
            DROP COLUMN IF EXISTS completed_at,
            DROP COLUMN IF EXISTS num_turns,
            DROP COLUMN IF EXISTS total_cost_usd,
            DROP COLUMN IF EXISTS repo_used;
        """
    )
