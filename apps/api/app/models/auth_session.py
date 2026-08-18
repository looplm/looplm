"""Refresh-session records backing refresh-token rotation and revocation.

One row per live refresh token, keyed by the token's ``jti``. Rotating a token revokes the row
and inserts a successor sharing its ``family_id``; presenting an already-revoked or unknown
``jti`` revokes the whole family, which is the standard response to a replayed refresh token
(either the client raced itself or the token was stolen).
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID

from app.models.models import Base


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    # The jti of the refresh token this row authorizes.
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Shared by every token in one rotation chain, so a replay can revoke the lineage.
    family_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
