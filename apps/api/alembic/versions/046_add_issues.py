"""Add issue clustering: issues, issue_evidence, issue_events.

An issue is a cluster of related production failures (explicit failures, eval
failures, negative feedback, anomalies) grouped into one named, prioritized
record with linked trace evidence and an append-only event timeline.

Revision ID: 046
Revises: 045
Create Date: 2026-06-03
"""
from typing import Sequence, Union

from alembic import op


revision: str = '046'
down_revision: Union[str, None] = '045'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum types (Postgres has no CREATE TYPE IF NOT EXISTS). On an already-running
    # instance these may exist from startup create_all, so guard each one.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE issue_severity AS ENUM ('high', 'medium', 'low');
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE issue_status AS ENUM
                ('open', 'diagnosing', 'resolving', 'resolved', 'recurring', 'dismissed');
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE signal_type AS ENUM
                ('explicit_failure', 'eval_failure', 'negative_feedback', 'anomaly');
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS issues (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            integration_id UUID REFERENCES integrations(id) ON DELETE SET NULL,
            title VARCHAR(512) NOT NULL,
            description TEXT,
            category VARCHAR(128),
            severity issue_severity NOT NULL DEFAULT 'medium',
            status issue_status NOT NULL DEFAULT 'open',
            signal_types JSONB NOT NULL DEFAULT '[]',
            fingerprint VARCHAR(256),
            root_cause TEXT,
            trace_count INTEGER NOT NULL DEFAULT 0,
            affected_pct DOUBLE PRECISION
                CHECK (affected_pct >= 0 AND affected_pct <= 100),
            first_seen_at TIMESTAMPTZ,
            last_seen_at TIMESTAMPTZ,
            resolved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_issues_project_id ON issues (project_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_issues_project_status ON issues (project_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_issues_integration_id ON issues (integration_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_issues_last_seen_at ON issues (last_seen_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS issue_evidence (
            id UUID PRIMARY KEY,
            issue_id UUID NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
            trace_id UUID REFERENCES traces(id) ON DELETE SET NULL,
            signal_type signal_type NOT NULL,
            detail TEXT,
            occurred_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_issue_evidence UNIQUE (issue_id, trace_id, signal_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_evidence_issue_id ON issue_evidence (issue_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_evidence_trace_id ON issue_evidence (trace_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS issue_events (
            id UUID PRIMARY KEY,
            issue_id UUID NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
            event_type VARCHAR(64) NOT NULL,
            detail JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_events_issue_id ON issue_events (issue_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS issue_events")
    op.execute("DROP TABLE IF EXISTS issue_evidence")
    op.execute("DROP TABLE IF EXISTS issues")
    op.execute("DROP TYPE IF EXISTS signal_type")
    op.execute("DROP TYPE IF EXISTS issue_status")
    op.execute("DROP TYPE IF EXISTS issue_severity")
