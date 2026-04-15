"""Add eval_jobs table for tracking triggered eval runs.

Revision ID: 010_add_eval_jobs
Revises: 009_add_evaluations
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "010_add_eval_jobs"
down_revision = "009_add_evaluations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    eval_job_status = sa.Enum("pending", "running", "completed", "failed", name="eval_job_status")
    eval_job_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "eval_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("test_suite", sa.String(255), nullable=False),
        sa.Column("status", eval_job_status, nullable=False, server_default=sa.text("'pending'")),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("eval_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_eval_jobs_project_id", "eval_jobs", ["project_id"])
    op.create_index("idx_eval_jobs_status", "eval_jobs", ["status"])
    op.create_index("idx_eval_jobs_started_at", "eval_jobs", [sa.text("started_at DESC")])


def downgrade() -> None:
    op.drop_index("idx_eval_jobs_started_at", table_name="eval_jobs")
    op.drop_index("idx_eval_jobs_status", table_name="eval_jobs")
    op.drop_index("idx_eval_jobs_project_id", table_name="eval_jobs")
    op.drop_table("eval_jobs")
    sa.Enum(name="eval_job_status").drop(op.get_bind(), checkfirst=True)
