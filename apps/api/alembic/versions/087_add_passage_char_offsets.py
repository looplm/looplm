"""Add document-anchored char offsets to passage_relevance_labels.

Each passage selection can now record ``char_start`` / ``char_end`` — the passage's
``[char_start, char_end)`` into the parsed document, derived by anchoring the local chunk split to
the chunk's own ``chunk_char_start`` from the index. These share the parsed-markdown coordinate
space, so a selection can be re-matched to a *new* chunking by offset overlap and survives
re-chunking. Both are nullable (NULL for legacy-chunker pages whose index docs carry no offset).

The app's startup ``create_all`` may already have added these columns in dev (see CLAUDE.md); this
revision guards each add so production upgrades apply them explicitly.

Revision ID: 087
Revises: 086
Create Date: 2026-07-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '087'
down_revision: Union[str, None] = '086'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "passage_relevance_labels"


def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names()


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_table(_TABLE):
        return
    if not _has_column(_TABLE, "char_start"):
        op.add_column(_TABLE, sa.Column("char_start", sa.Integer(), nullable=True))
    if not _has_column(_TABLE, "char_end"):
        op.add_column(_TABLE, sa.Column("char_end", sa.Integer(), nullable=True))


def downgrade() -> None:
    if not _has_table(_TABLE):
        return
    if _has_column(_TABLE, "char_end"):
        op.drop_column(_TABLE, "char_end")
    if _has_column(_TABLE, "char_start"):
        op.drop_column(_TABLE, "char_start")
