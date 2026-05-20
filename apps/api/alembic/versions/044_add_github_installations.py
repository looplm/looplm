"""Add github_installations table for the Code Agent GitHub bridge.

Revision ID: 044
Revises: 043
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op


revision: str = '044'
down_revision: Union[str, None] = '043'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS github_installations (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            installation_id BIGINT NOT NULL,
            account_login VARCHAR(255) NOT NULL,
            account_type VARCHAR(32) NOT NULL DEFAULT 'User',
            repo_full_name VARCHAR(512),
            repo_default_branch VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_github_installations_project_id UNIQUE (project_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_github_installations_installation_id "
        "ON github_installations (installation_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS github_installations")
