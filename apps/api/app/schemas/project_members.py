"""Schemas for project member management API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.project_member import ALL_SECTIONS


class MemberInvite(BaseModel):
    email: EmailStr
    role: str = Field("member", pattern="^(admin|member)$")
    allowed_sections: list[str] = Field(default_factory=lambda: list(ALL_SECTIONS))
    allowed_pages: list[str] | None = None


class MemberUpdate(BaseModel):
    role: str | None = Field(None, pattern="^(admin|member)$")
    allowed_sections: list[str] | None = None
    allowed_pages: list[str] | None = Field(None)


class MemberResponse(BaseModel):
    id: UUID
    user_id: UUID | None = None
    email: str
    role: str
    allowed_sections: list[str]
    allowed_pages: list[str] | None = None
    status: str = "active"
    created_at: datetime


class InviteResponse(BaseModel):
    """Returned from the invite endpoint."""
    id: UUID
    email: str
    role: str
    allowed_sections: list[str]
    allowed_pages: list[str] | None = None
    status: str  # "active" or "pending"
    invite_link: str | None = None
    email_sent: bool = False


class MemberListResponse(BaseModel):
    data: list[MemberResponse]


class PermissionsResponse(BaseModel):
    role: str
    allowed_sections: list[str]
    allowed_pages: list[str] | None = None
