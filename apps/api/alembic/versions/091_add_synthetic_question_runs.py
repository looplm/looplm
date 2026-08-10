"""Add synthetic_question_runs table.

Backs the "generate test questions from index chunks" job: sample chunks from an index
provider, draft questions the LLM grounds in each chunk, and persist them as a test dataset
whose ground truth is the source chunk. The run row carries the request, the progress counters
the UI polls, and the generated questions (which is also the whole payload for a preview run,
where nothing is persisted).

The app's startup ``create_all`` may already have created this table in dev (see CLAUDE.md);
this revision exists so production upgrades create it explicitly. Guarded so it no-ops if the
table already exists.

Revision ID: 091
Revises: 090
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "091"
down_revision = "090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())

    if not inspector.has_table("synthetic_question_runs"):
        op.create_table(
            "synthetic_question_runs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider_id", UUID(as_uuid=True), sa.ForeignKey("index_providers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("stage", sa.String(64), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("scope", sa.String(32), nullable=False, server_default=sa.text("'corpus'")),
            sa.Column("partition_key", sa.String(255), nullable=True),
            sa.Column("partition_value", sa.Text(), nullable=True),
            sa.Column("sample_size", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("questions_per_chunk", sa.Integer(), nullable=False, server_default=sa.text("2")),
            sa.Column("negative_share", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("verify_negatives", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("persist", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("dataset_id", UUID(as_uuid=True), nullable=True),
            sa.Column("dataset_name", sa.String(255), nullable=True),
            sa.Column("total", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("results", JSONB, nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )

    # Re-inspect: the table above may have been created in this transaction, so the inspector's
    # cached table list is stale for the index lookup below.
    inspector = inspect(op.get_bind())
    index = "idx_synthetic_question_runs_lookup"
    if index not in {ix["name"] for ix in inspector.get_indexes("synthetic_question_runs")}:
        op.create_index(index, "synthetic_question_runs", ["project_id", "provider_id"])


def downgrade() -> None:
    op.drop_index("idx_synthetic_question_runs_lookup", table_name="synthetic_question_runs")
    op.drop_table("synthetic_question_runs")
