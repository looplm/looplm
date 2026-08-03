"""User directory models — names for raw end-user ids, and groups of them.

Observe surfaces key everything on ``Trace.user_id``, an opaque string coming from the
instrumented app. A ``UserIdentity`` gives one or more of those ids a human-readable name
(the same person often has several ids), and a ``UserGroup`` collects identities and/or raw
ids into something filterable, e.g. "Internal QA".

Member lists are JSONB arrays rather than join tables: membership is resolved in the client
(and, when needed, in Python) instead of in SQL, so joins buy nothing, and the test suite runs
on SQLite where ``JSONB`` compiles to ``TEXT`` and JSON operators are unavailable. The
consequence is that the "a raw user id belongs to at most one identity per project" rule is
enforced by the router (409 DUPLICATE), not by a unique constraint — see
``app/routers/user_directory.py``.
"""

from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class UserIdentity(Base):
    """A named person, mapping to one or more raw ``Trace.user_id`` values."""

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_user_identities_project_name"),
        Index("idx_user_identities_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    # Raw Trace.user_id strings belonging to this person.
    user_ids = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")


class UserGroup(Base):
    """A filterable set of identities and/or raw user ids, e.g. "Internal QA"."""

    __tablename__ = "user_groups"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_user_groups_project_name"),
        Index("idx_user_groups_project_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    # UserIdentity ids (as strings), pruned when an identity is deleted.
    identity_ids = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    # Raw Trace.user_id strings added straight to the group, without a named identity.
    user_ids = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    project = relationship("Project")
