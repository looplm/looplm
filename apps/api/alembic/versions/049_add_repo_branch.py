"""Add a selectable sync branch to GitHub installations.

`github_installations.repo_branch` stores the branch the user chose to sync.
It falls back to `repo_default_branch` (the repo's own default) when unset, so
existing rows keep cloning the default branch with no backfill needed.

Revision ID: 049
Revises: 048
Create Date: 2026-06-04
"""
from typing import Sequence, Union

from alembic import op


revision: str = '049'
down_revision: Union[str, None] = '048'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE github_installations ADD COLUMN IF NOT EXISTS repo_branch VARCHAR(255)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE github_installations DROP COLUMN IF EXISTS repo_branch")
