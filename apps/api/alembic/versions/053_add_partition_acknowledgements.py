"""Add partition_acknowledgements table for RAG-coverage issue "memory".

Stores per-project, per-(provider, partition_key, partition_value) records that
a flagged partition value is intentional, so quality flags can be muted on
future coverage runs.

Revision ID: 053
Revises: 052
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op


revision: str = '053'
down_revision: Union[str, None] = '052'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS partition_acknowledgements (
            id UUID DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            provider_id UUID NOT NULL REFERENCES index_providers(id) ON DELETE CASCADE,
            partition_key VARCHAR(255) NOT NULL,
            partition_value TEXT NOT NULL,
            note TEXT,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_partition_ack
                UNIQUE (project_id, provider_id, partition_key, partition_value)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_partition_acks_lookup
        ON partition_acknowledgements (project_id, provider_id, partition_key)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS partition_acknowledgements")
