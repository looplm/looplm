"""Add projects table, migrate integrations from owner_id to project_id.

Revision ID: 007_add_projects
Revises: 006_add_feedback_scores
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "007_add_projects"
down_revision = "006_add_feedback_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create projects table
    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_projects_owner_id", "projects", ["owner_id"])

    # 2. Add project_id column (nullable initially)
    op.add_column("integrations", sa.Column("project_id", UUID(as_uuid=True), nullable=True))

    # 3. Data migration: create a "Default" project for each user who has integrations
    #    and assign their integrations to that project
    conn = op.get_bind()

    # Create default project for every distinct owner_id in integrations
    conn.execute(sa.text("""
        INSERT INTO projects (id, owner_id, name)
        SELECT gen_random_uuid(), owner_id, 'Default'
        FROM integrations
        GROUP BY owner_id
    """))

    # Also create a default project for users who have no integrations
    conn.execute(sa.text("""
        INSERT INTO projects (id, owner_id, name)
        SELECT gen_random_uuid(), u.id, 'Default'
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM projects p WHERE p.owner_id = u.id
        )
    """))

    # Set project_id on integrations to match their owner's default project
    conn.execute(sa.text("""
        UPDATE integrations i
        SET project_id = p.id
        FROM projects p
        WHERE p.owner_id = i.owner_id
    """))

    # 4. Make project_id NOT NULL and add FK
    op.alter_column("integrations", "project_id", nullable=False)
    op.create_foreign_key(
        "fk_integrations_project_id",
        "integrations",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("idx_integrations_project_id", "integrations", ["project_id"])

    # 5. Drop owner_id column and its index
    op.drop_index("ix_integrations_owner_id", table_name="integrations")
    op.drop_column("integrations", "owner_id")


def downgrade() -> None:
    # Re-add owner_id column
    op.add_column("integrations", sa.Column("owner_id", UUID(as_uuid=True), nullable=True))

    # Restore owner_id from project's owner_id
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE integrations i
        SET owner_id = p.owner_id
        FROM projects p
        WHERE p.id = i.project_id
    """))

    op.alter_column("integrations", "owner_id", nullable=False)
    op.create_index("ix_integrations_owner_id", "integrations", ["owner_id"])

    # Drop project_id FK and column
    op.drop_index("idx_integrations_project_id", table_name="integrations")
    op.drop_constraint("fk_integrations_project_id", "integrations", type_="foreignkey")
    op.drop_column("integrations", "project_id")

    # Drop projects table
    op.drop_index("idx_projects_owner_id", table_name="projects")
    op.drop_table("projects")
