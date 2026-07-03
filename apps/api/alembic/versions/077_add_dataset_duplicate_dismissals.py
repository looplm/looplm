"""Add dataset_duplicate_dismissals table.

Revision ID: 077
Revises: 076
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_duplicate_dismissals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id_a", UUID(as_uuid=True), sa.ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id_b", UUID(as_uuid=True), sa.ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "case_id_a", "case_id_b", name="uq_dup_dismissal_pair"),
    )
    op.create_index("idx_dup_dismissal_project_id", "dataset_duplicate_dismissals", ["project_id"])


def downgrade() -> None:
    op.drop_index("idx_dup_dismissal_project_id", table_name="dataset_duplicate_dismissals")
    op.drop_table("dataset_duplicate_dismissals")
