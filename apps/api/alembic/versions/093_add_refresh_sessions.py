"""Add refresh_sessions table.

Backs refresh-token rotation and revocation: one row per live refresh token, keyed by the
token's jti. Before this, a refresh token was a stateless 7-day bearer with no way to revoke it
and no logout endpoint.

The app's startup ``create_all`` may already have created this table in dev (see CLAUDE.md);
this revision exists so production upgrades create it explicitly. Guarded so it no-ops if the
table already exists.

Revision ID: 093
Revises: 092
Create Date: 2026-08-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "093"
down_revision = "092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "refresh_sessions" in inspect(bind).get_table_names():
        return

    op.create_table(
        "refresh_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])
    op.create_index("ix_refresh_sessions_family_id", "refresh_sessions", ["family_id"])
    op.create_index("ix_refresh_sessions_expires_at", "refresh_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("refresh_sessions")
