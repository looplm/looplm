"""Add first-party tracing ingest: looplm integration type, ingest_keys, last_received_at.

Revision ID: 045
Revises: 044
Create Date: 2026-06-03
"""
from typing import Sequence, Union

from alembic import op


revision: str = '045'
down_revision: Union[str, None] = '044'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New enum value. ALTER TYPE ... ADD VALUE cannot run inside a transaction
    # block, so use Alembic's autocommit block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE integration_type ADD VALUE IF NOT EXISTS 'looplm'")

    # Push-based liveness for looplm integrations.
    op.execute(
        "ALTER TABLE integrations ADD COLUMN IF NOT EXISTS last_received_at TIMESTAMPTZ"
    )

    # Ingest keys (machine auth for the tracing SDK). We store only a sha256
    # hash of the key plus a short display prefix.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ingest_keys (
            id UUID PRIMARY KEY,
            integration_id UUID NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL DEFAULT 'default',
            key_hash VARCHAR(64) NOT NULL UNIQUE,
            key_prefix VARCHAR(16) NOT NULL,
            last_used_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingest_keys_integration_id "
        "ON ingest_keys (integration_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ingest_keys")
    op.execute("ALTER TABLE integrations DROP COLUMN IF EXISTS last_received_at")
    # Note: Postgres cannot drop an enum value; 'looplm' remains on integration_type.
