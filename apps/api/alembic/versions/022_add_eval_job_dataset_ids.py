"""Add dataset_ids JSONB column to eval_jobs and make test_suite have a default.

Revision ID: 022
Revises: 021
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("eval_jobs", sa.Column("dataset_ids", JSONB, nullable=True))
    op.alter_column("eval_jobs", "test_suite", server_default=sa.text("''"), nullable=False)


def downgrade() -> None:
    op.drop_column("eval_jobs", "dataset_ids")
    op.alter_column("eval_jobs", "test_suite", server_default=None, nullable=False)
