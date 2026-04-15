"""Add evaluators table.

Revision ID: 013_add_evaluators
Revises: 012_add_eval_job_log_progress
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "013_add_evaluators"
down_revision = "012_add_eval_job_log_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DO $$ BEGIN CREATE TYPE evaluator_type AS ENUM ('llm_judge', 'deterministic', 'hybrid'); EXCEPTION WHEN duplicate_object THEN null; END $$")

    evaluator_type = sa.Enum("llm_judge", "deterministic", "hybrid", name="evaluator_type", create_type=False)

    op.create_table(
        "evaluators",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("type", evaluator_type, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("relevance", sa.String(32), nullable=False, server_default="medium"),
        sa.Column("affects_pass", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source", sa.String(128), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("idx_evaluators_project_id", "evaluators", ["project_id"])
    op.create_unique_constraint("uq_evaluators_project_name", "evaluators", ["project_id", "name"])


def downgrade() -> None:
    op.drop_table("evaluators")
    sa.Enum(name="evaluator_type").drop(op.get_bind(), checkfirst=True)
