"""Add eval_runs and eval_results tables for evaluation tracking.

Revision ID: 009_add_evaluations
Revises: 008_add_advisor_analyses
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "009_add_evaluations"
down_revision = "008_add_advisor_analyses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("source", sa.String(255)),
        sa.Column("tags", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("total", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("passed", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("failed", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("grader_summary", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("score_summary", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_eval_runs_project_id", "eval_runs", ["project_id"])
    op.create_index("idx_eval_runs_created_at", "eval_runs", [sa.text("created_at DESC")])

    op.create_table(
        "eval_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("eval_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("test_id", sa.String(512), nullable=False),
        sa.Column("pass", sa.Boolean, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("input", sa.Text),
        sa.Column("output", sa.Text),
        sa.Column("expected_output", sa.Text),
        sa.Column("tags", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("graders", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("scores", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_eval_results_run_id", "eval_results", ["run_id"])
    op.create_index("idx_eval_results_pass", "eval_results", ["run_id", "pass"])


def downgrade() -> None:
    op.drop_index("idx_eval_results_pass", table_name="eval_results")
    op.drop_index("idx_eval_results_run_id", table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_index("idx_eval_runs_created_at", table_name="eval_runs")
    op.drop_index("idx_eval_runs_project_id", table_name="eval_runs")
    op.drop_table("eval_runs")
