"""Add validation sign-off columns to test_cases.

Lets a reviewer mark a test case as validated and records who validated it and when.
``validated`` is orthogonal to ``status`` (active/needs_work); ``validated_by`` FKs users
with ``ondelete=SET NULL`` so deleting a user preserves the case but drops attribution.

The app's startup ``create_all`` may already have added these columns in dev (see CLAUDE.md);
this revision exists so production upgrades add them explicitly. Guarded so it no-ops if the
columns already exist.

Revision ID: 089
Revises: 088
Create Date: 2026-07-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = '089'
down_revision: Union[str, None] = '088'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "test_cases" not in sa.inspect(op.get_bind()).get_table_names():
        return
    existing = _columns("test_cases")
    if "validated" not in existing:
        op.add_column(
            "test_cases",
            sa.Column(
                "validated", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
        )
    if "validated_by" not in existing:
        op.add_column(
            "test_cases",
            sa.Column(
                "validated_by",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if "validated_at" not in existing:
        op.add_column(
            "test_cases",
            sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    existing = _columns("test_cases")
    if "validated_at" in existing:
        op.drop_column("test_cases", "validated_at")
    if "validated_by" in existing:
        op.drop_column("test_cases", "validated_by")
    if "validated" in existing:
        op.drop_column("test_cases", "validated")
