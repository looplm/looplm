"""Add feedback_scores table.

Revision ID: 006
Revises: 005_add_prompt_reviews
Create Date: 2026-03-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "006_add_feedback_scores"
down_revision = "005_add_prompt_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_scores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("integration_id", UUID(as_uuid=True), sa.ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trace_id", UUID(as_uuid=True), sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("external_trace_id", sa.String(512), nullable=False),
        sa.Column("score_name", sa.String(128), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("data_type", sa.String(32), nullable=False, server_default=sa.text("'BOOLEAN'")),
        sa.Column("comment", sa.Text),
        sa.Column("scored_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("integration_id", "external_id"),
    )
    op.create_index("idx_feedback_scores_trace_id_name", "feedback_scores", ["trace_id", "score_name"])
    op.create_index("idx_feedback_scores_name_value", "feedback_scores", ["score_name", "value"])
    op.create_index("idx_feedback_scores_scored_at", "feedback_scores", [sa.text("scored_at DESC")])


def downgrade() -> None:
    op.drop_index("idx_feedback_scores_scored_at")
    op.drop_index("idx_feedback_scores_name_value")
    op.drop_index("idx_feedback_scores_trace_id_name")
    op.drop_table("feedback_scores")
