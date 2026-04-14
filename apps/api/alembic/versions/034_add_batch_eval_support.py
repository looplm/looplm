"""Add batch eval support — batch_eval_jobs table, batch_pending status, FK on eval_jobs.

Revision ID: 034
Revises: 033
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op


revision: str = '034'
down_revision: Union[str, None] = '033'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add batch_pending to eval_job_status enum
    op.execute("ALTER TYPE eval_job_status ADD VALUE IF NOT EXISTS 'batch_pending' AFTER 'running'")

    # Create batch_eval_jobs table (IF NOT EXISTS for idempotency — table may
    # already exist from SQLAlchemy's create_all at startup)
    op.execute("""
        CREATE TABLE IF NOT EXISTS batch_eval_jobs (
            id UUID DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            eval_job_id UUID NOT NULL REFERENCES eval_jobs(id) ON DELETE CASCADE,
            run_id UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            batch_id VARCHAR(255),
            input_file_id VARCHAR(255),
            status VARCHAR(50) NOT NULL DEFAULT 'preparing',
            total_requests INTEGER NOT NULL DEFAULT 0,
            completed_requests INTEGER NOT NULL DEFAULT 0,
            failed_requests INTEGER NOT NULL DEFAULT 0,
            request_mapping JSONB NOT NULL DEFAULT '{}',
            error TEXT,
            submitted_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_batch_eval_jobs_status ON batch_eval_jobs (status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_batch_eval_jobs_eval_job_id ON batch_eval_jobs (eval_job_id)")

    # Add batch_eval_job_id FK on eval_jobs
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'eval_jobs' AND column_name = 'batch_eval_job_id'
            ) THEN
                ALTER TABLE eval_jobs
                ADD COLUMN batch_eval_job_id UUID REFERENCES batch_eval_jobs(id) ON DELETE SET NULL;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_column('eval_jobs', 'batch_eval_job_id')
    op.drop_index('idx_batch_eval_jobs_eval_job_id', table_name='batch_eval_jobs')
    op.drop_index('idx_batch_eval_jobs_status', table_name='batch_eval_jobs')
    op.drop_table('batch_eval_jobs')
    # Note: cannot remove enum value in PostgreSQL without recreating the type
