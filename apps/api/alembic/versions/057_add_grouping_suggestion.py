"""Add cached grouping suggestion columns to index_providers.

Stores the LLM-suggested grouping hierarchy + metadata hints (the Data Sources
"grouping advisor") so it survives reloads and is only recomputed on demand.

Revision ID: 057
Revises: 056
Create Date: 2026-06-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = '057'
down_revision: Union[str, None] = '056'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("index_providers", sa.Column("grouping_suggestion", JSONB, nullable=True))
    op.add_column(
        "index_providers",
        sa.Column("grouping_suggested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("index_providers", "grouping_suggested_at")
    op.drop_column("index_providers", "grouping_suggestion")
