"""Add expected_page_urls and expected_source_types to test_cases.

Revision ID: 021
Revises: 020
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("test_cases", sa.Column("expected_page_urls", JSONB, nullable=False, server_default=sa.text("'[]'")))
    op.add_column("test_cases", sa.Column("expected_source_types", JSONB, nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    op.drop_column("test_cases", "expected_source_types")
    op.drop_column("test_cases", "expected_page_urls")
