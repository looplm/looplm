"""Backfill project_members.write_pages / project_invitations.write_pages.

``require_write`` used to treat a NULL ``write_pages`` as "legacy full write". That default,
combined with the registration path never copying ``write_pages`` off an invitation, silently
gave every invited member write access to all of their allowed pages. The check now fails
closed, so existing NULLs must be materialised or members would lose access they had.

Members keep exactly the effective access they have today (their allowed pages, or every page
when unrestricted). Pending invitations become read-only, which is what ``invite_member``
already intends when the caller omits ``write_pages``.

Revision ID: 092
Revises: 091
Create Date: 2026-08-18
"""

import json

from alembic import op
import sqlalchemy as sa

from app.models.project_member import ALL_PAGES

revision = "092"
down_revision = "091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    all_pages = json.dumps(ALL_PAGES)
    op.execute(
        sa.text(
            "UPDATE project_members "
            "SET write_pages = COALESCE(allowed_pages, CAST(:all_pages AS jsonb)) "
            "WHERE write_pages IS NULL"
        ).bindparams(all_pages=all_pages)
    )
    op.execute(
        "UPDATE project_invitations SET write_pages = '[]'::jsonb WHERE write_pages IS NULL"
    )


def downgrade() -> None:
    # Irreversible by design: the pre-migration state cannot be distinguished from an
    # explicitly-granted identical set, and restoring NULL would re-open full write access.
    pass
