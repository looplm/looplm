"""Add user_identities and user_groups tables.

Lets a project name raw ``Trace.user_id`` values, group several ids under one person, and
collect identities/ids into filterable groups (e.g. "Internal QA"). Member lists are JSONB
arrays; uniqueness of "one id per identity" is enforced in the router, not the schema.

The app's startup ``create_all`` may already have created these tables in dev (see CLAUDE.md);
this revision exists so production upgrades create them explicitly. Guarded so it no-ops if the
tables already exist.

Revision ID: 090
Revises: 089
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "090"
down_revision = "089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())

    if not inspector.has_table("user_identities"):
        op.create_table(
            "user_identities",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("user_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("project_id", "name", name="uq_user_identities_project_name"),
        )

    if not inspector.has_table("user_groups"):
        op.create_table(
            "user_groups",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("identity_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("user_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("project_id", "name", name="uq_user_groups_project_name"),
        )

    # Re-inspect: the tables above may have been created in this transaction, so the
    # inspector's cached table list is stale for the index lookups below.
    inspector = inspect(op.get_bind())
    for table, index in (
        ("user_identities", "idx_user_identities_project_id"),
        ("user_groups", "idx_user_groups_project_id"),
    ):
        if index not in {ix["name"] for ix in inspector.get_indexes(table)}:
            op.create_index(index, table, ["project_id"])


def downgrade() -> None:
    op.drop_index("idx_user_groups_project_id", table_name="user_groups")
    op.drop_table("user_groups")
    op.drop_index("idx_user_identities_project_id", table_name="user_identities")
    op.drop_table("user_identities")
