"""ProjectInvitation model for pending invites to non-existing users."""

import secrets
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.models import Base


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


class ProjectInvitation(Base):
    __tablename__ = "project_invitations"
    __table_args__ = (
        UniqueConstraint("project_id", "email", name="uq_project_invitations_project_email"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invited_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email = Column(String(255), nullable=False, index=True)
    token = Column(String(64), nullable=False, unique=True, default=_generate_token)
    role = Column(String(20), nullable=False, server_default=text("'member'"))
    allowed_sections = Column(
        JSONB, nullable=False, server_default=text("'[\"observe\",\"evaluate\",\"improve\"]'::jsonb")
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
