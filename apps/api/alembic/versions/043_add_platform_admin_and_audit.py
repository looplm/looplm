"""Add users.is_platform_admin column and admin_audit table.

Revision ID: 043
Revises: 042
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op


revision: str = '043'
down_revision: Union[str, None] = '042'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT false"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit (
            id UUID PRIMARY KEY,
            user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            action VARCHAR(64) NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_audit_user_id ON admin_audit (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_audit_action ON admin_audit (action)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_admin_audit_action")
    op.execute("DROP INDEX IF EXISTS ix_admin_audit_user_id")
    op.execute("DROP TABLE IF EXISTS admin_audit")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_platform_admin")
