"""Add advisor_analyses table for persisting architecture advisor results.

Revision ID: 008_add_advisor_analyses
Revises: 007_add_projects
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "008_add_advisor_analyses"
down_revision = "007_add_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "advisor_analyses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "integration_id",
            UUID(as_uuid=True),
            sa.ForeignKey("integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("suggestions", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_advisor_analyses_integration_id", "advisor_analyses", ["integration_id"])


def downgrade() -> None:
    op.drop_index("idx_advisor_analyses_integration_id", table_name="advisor_analyses")
    op.drop_table("advisor_analyses")
