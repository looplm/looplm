"""Add json_file to integration_type enum.

Revision ID: 015_add_json_file_type
Revises: 014_add_test_datasets
Create Date: 2026-03-17
"""

from alembic import op

revision = "015_add_json_file_type"
down_revision = "014_add_test_datasets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE integration_type ADD VALUE IF NOT EXISTS 'json_file'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; the value is harmless if unused.
    pass
