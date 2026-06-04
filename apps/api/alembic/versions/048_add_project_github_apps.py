"""Add per-project GitHub App identities.

`project_github_apps` holds each project's own GitHub App credentials (App id,
OAuth client id/secret, signing private key). client_secret and private_key are
stored encrypted at the app layer (BYTEA). A project without a row falls back to
the instance-wide GITHUB_APP_* env settings.

Revision ID: 048
Revises: 047
Create Date: 2026-06-03
"""
from typing import Sequence, Union

from alembic import op


revision: str = '048'
down_revision: Union[str, None] = '047'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_github_apps (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            app_id VARCHAR(64) NOT NULL,
            app_name VARCHAR(255),
            client_id VARCHAR(255) NOT NULL,
            client_secret BYTEA NOT NULL,
            private_key BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_project_github_apps_project_id UNIQUE (project_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_github_apps")
