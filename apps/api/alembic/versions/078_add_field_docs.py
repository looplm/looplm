"""Add cached field-documentation columns to index_providers.

Stores the LLM-generated field docs (per-field purpose + groups of confusable
fields) for the Data Sources "Fields" tab, so they survive reloads and are only
recomputed on demand. Mirrors the grouping-suggestion cache (revision 057).

Revision ID: 078
Revises: 077
Create Date: 2026-07-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "078"
down_revision: Union[str, None] = "077"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = {c["name"] for c in inspect(op.get_bind()).get_columns("index_providers")}
    if "field_docs" not in existing:
        op.add_column("index_providers", sa.Column("field_docs", JSONB, nullable=True))
    if "field_docs_generated_at" not in existing:
        op.add_column(
            "index_providers",
            sa.Column("field_docs_generated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("index_providers", "field_docs_generated_at")
    op.drop_column("index_providers", "field_docs")
