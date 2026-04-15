"""Normalize evaluator source values to allowed set.

Revision ID: 016_normalize_evaluator_source
Revises: 015_add_json_file_type
Create Date: 2026-03-17
"""

from alembic import op

revision = "016_normalize_evaluator_source"
down_revision = "015_add_json_file_type"
branch_labels = None
depends_on = None

ALLOWED_SOURCES = ("custom", "ragas", "langfuse", "discovered")


def upgrade() -> None:
    op.execute(
        f"UPDATE evaluators SET source = 'discovered' "
        f"WHERE source IS NOT NULL AND source NOT IN ({', '.join(repr(s) for s in ALLOWED_SOURCES)})"
    )


def downgrade() -> None:
    pass  # non-reversible data migration
