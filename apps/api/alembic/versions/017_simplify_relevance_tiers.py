"""Simplify relevance from 4 tiers to 3: core / important / minor.

Revision ID: 017_simplify_relevance_tiers
Revises: 016_normalize_evaluator_source
Create Date: 2026-03-17
"""

from alembic import op

revision = "017_simplify_relevance_tiers"
down_revision = "016_normalize_evaluator_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE evaluators SET relevance = 'core' WHERE relevance IN ('critical', 'high')")
    op.execute("UPDATE evaluators SET relevance = 'important' WHERE relevance = 'medium'")
    op.execute("UPDATE evaluators SET relevance = 'minor' WHERE relevance = 'low'")
    op.execute("ALTER TABLE evaluators ALTER COLUMN relevance SET DEFAULT 'important'")


def downgrade() -> None:
    op.execute("UPDATE evaluators SET relevance = 'critical' WHERE relevance = 'core'")
    op.execute("UPDATE evaluators SET relevance = 'medium' WHERE relevance = 'important'")
    op.execute("UPDATE evaluators SET relevance = 'low' WHERE relevance = 'minor'")
    op.execute("ALTER TABLE evaluators ALTER COLUMN relevance SET DEFAULT 'medium'")
