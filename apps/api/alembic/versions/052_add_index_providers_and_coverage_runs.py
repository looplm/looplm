"""Add index_providers + coverage_runs tables for RAG eval-coverage.

index_providers: per-project read-only connections to a retrieval backend
(Azure AI Search today). coverage_runs: background coverage-analysis jobs over
one partition key, persisting results and LLM-drafted eval suggestions.

Revision ID: 052
Revises: 051
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = '052'
down_revision: Union[str, None] = '051'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum type (CREATE TYPE has no IF NOT EXISTS — guard with a DO block).
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE index_provider_type AS ENUM ('azure_search', 'pinecone', 'qdrant', 'pgvector');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS index_providers (
            id UUID DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            type index_provider_type NOT NULL,
            name VARCHAR(255) NOT NULL,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            api_key BYTEA NOT NULL,
            base_url VARCHAR(2048),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_index_providers_project_id
        ON index_providers (project_id)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS coverage_runs (
            id UUID DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            provider_id UUID NOT NULL REFERENCES index_providers(id) ON DELETE CASCADE,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            error TEXT,
            partition_key VARCHAR(255) NOT NULL,
            dataset_ids JSONB,
            suggest VARCHAR(8) NOT NULL DEFAULT 'false',
            min_covering_cases INTEGER NOT NULL DEFAULT 1,
            total INTEGER NOT NULL DEFAULT 0,
            processed INTEGER NOT NULL DEFAULT 0,
            results JSONB,
            suggestions JSONB NOT NULL DEFAULT '[]'::jsonb,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_coverage_runs_project_id
        ON coverage_runs (project_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS coverage_runs")
    op.execute("DROP TABLE IF EXISTS index_providers")
    op.execute("DROP TYPE IF EXISTS index_provider_type")
