"""Add json_imports table for import history tracking.

Revision ID: 018_add_json_imports_table
Revises: 017_simplify_relevance_tiers
Create Date: 2026-03-17
"""

import sqlalchemy as sa
from alembic import op

revision = "018_add_json_imports_table"
down_revision = "017_simplify_relevance_tiers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_import_status = sa.Enum("success", "partial", "error", name="json_import_status")
    json_import_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "json_imports",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("record_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("status", json_import_status, nullable=False, server_default=sa.text("'success'")),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_json_imports_project_id", "json_imports", ["project_id"])
    op.create_index("idx_json_imports_created_at", "json_imports", [sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_table("json_imports")
    sa.Enum(name="json_import_status").drop(op.get_bind(), checkfirst=True)
