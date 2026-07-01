"""Retrieval vs generation category on evaluators.

Adds a non-null ``category`` column to evaluators (default 'generation') so the evaluators UI can
split them into a Retrieval group (did we fetch the right context) and a Generation group (did the
model use it well). Backfills the known retrieval evaluators — the source-retrieval check and the
image checks, plus any deterministic evaluator whose check_type inspects retrieved context.

Revision ID: 072
Revises: 071
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '072'
down_revision: Union[str, None] = '071'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "evaluators" not in sa.inspect(bind).get_table_names():
        return
    if "category" not in _columns("evaluators"):
        op.add_column(
            "evaluators",
            sa.Column(
                "category",
                sa.String(length=32),
                nullable=False,
                server_default="generation",
            ),
        )
    # Backfill known retrieval evaluators. Names cover the built-ins; the check_type clause catches
    # custom/discovered deterministic evaluators that inspect retrieved context.
    bind.execute(
        sa.text(
            """
            UPDATE evaluators
               SET category = 'retrieval'
             WHERE name IN ('sourceRetrieval', 'imageMissing', 'imageOrdering')
                OR config->>'check_type' IN
                   ('contains_urls', 'contains_sources', 'image_missing', 'image_ordering')
            """
        )
    )


def downgrade() -> None:
    if "category" in _columns("evaluators"):
        op.drop_column("evaluators", "category")
