"""Add prompt_reviews table.

Revision ID: 005
Revises: 004_add_child_run_support
Create Date: 2026-02-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "005_add_prompt_reviews"
down_revision = "004_add_child_run_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_reviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("prompt_id", UUID(as_uuid=True), sa.ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("anti_patterns", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("suggestions", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("rewritten_prompt", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("model", sa.String(256), nullable=False, server_default=sa.text("''")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_prompt_reviews_prompt_id", "prompt_reviews", ["prompt_id"])


def downgrade() -> None:
    op.drop_index("idx_prompt_reviews_prompt_id")
    op.drop_table("prompt_reviews")
