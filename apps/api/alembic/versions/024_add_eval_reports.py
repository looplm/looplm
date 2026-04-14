"""Add eval_reports table for persisting generated reports.

Revision ID: 024
Revises: 023
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eval_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("report_type", sa.String(32), nullable=False, server_default=sa.text("'multi_run'")),
        sa.Column("markdown", sa.Text, nullable=False),
        sa.Column("run_ids", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("run_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("total_tests", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_eval_reports_project_id", "eval_reports", ["project_id"])
    op.create_index("idx_eval_reports_created_at", "eval_reports", [sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("idx_eval_reports_created_at", table_name="eval_reports")
    op.drop_index("idx_eval_reports_project_id", table_name="eval_reports")
    op.drop_table("eval_reports")
