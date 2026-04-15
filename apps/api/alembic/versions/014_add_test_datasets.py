"""Add test_datasets and test_cases tables.

Revision ID: 014_add_test_datasets
Revises: 013_add_evaluators
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "014_add_test_datasets"
down_revision = "013_add_evaluators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "test_datasets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("tags", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_test_datasets_project_id", "test_datasets", ["project_id"])

    op.create_table(
        "test_cases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("dataset_id", UUID(as_uuid=True), sa.ForeignKey("test_datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("test_id", sa.String(255), nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("expected_answer", sa.Text, nullable=True),
        sa.Column("expected_sources", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("context_filters", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("team_filter", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("tag_filter", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("message_count", sa.Integer, nullable=True),
        sa.Column("has_summary", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("folder", sa.String(255), nullable=True),
        sa.Column("document", sa.String(255), nullable=True),
        sa.Column("source_feedback_id", UUID(as_uuid=True), nullable=True),
        sa.Column("source_trace_id", UUID(as_uuid=True), nullable=True),
        sa.Column("tags", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_test_cases_dataset_id", "test_cases", ["dataset_id"])


def downgrade() -> None:
    op.drop_table("test_cases")
    op.drop_table("test_datasets")
