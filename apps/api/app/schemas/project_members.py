"""Schemas for project member management API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.project_member import ALL_SECTIONS


def _check_write_subset(allowed_pages: list[str] | None, write_pages: list[str] | None) -> None:
    """write_pages must be a subset of allowed_pages when both are non-null."""
    if write_pages is None or allowed_pages is None:
        return
    orphans = set(write_pages) - set(allowed_pages)
    if orphans:
        raise ValueError(
            f"write_pages must be a subset of allowed_pages; unknown entries: {sorted(orphans)}"
        )


class MemberInvite(BaseModel):
    email: EmailStr
    role: str = Field("member", pattern="^(admin|member)$")
    allowed_sections: list[str] = Field(default_factory=lambda: list(ALL_SECTIONS))
    allowed_pages: list[str] | None = None
    write_pages: list[str] | None = None

    @model_validator(mode="after")
    def _validate_writes(self) -> "MemberInvite":
        _check_write_subset(self.allowed_pages, self.write_pages)
        return self


class MemberUpdate(BaseModel):
    role: str | None = Field(None, pattern="^(admin|member)$")
    allowed_sections: list[str] | None = None
    allowed_pages: list[str] | None = Field(None)
    write_pages: list[str] | None = Field(None)

    @model_validator(mode="after")
    def _validate_writes(self) -> "MemberUpdate":
        _check_write_subset(self.allowed_pages, self.write_pages)
        return self


class MemberResponse(BaseModel):
    id: UUID
    user_id: UUID | None = None
    email: str
    role: str
    allowed_sections: list[str]
    allowed_pages: list[str] | None = None
    write_pages: list[str] | None = None
    status: str = "active"
    created_at: datetime


class InviteResponse(BaseModel):
    """Returned from the invite endpoint."""
    id: UUID
    email: str
    role: str
    allowed_sections: list[str]
    allowed_pages: list[str] | None = None
    write_pages: list[str] | None = None
    status: str  # "active" or "pending"
    invite_link: str | None = None
    email_sent: bool = False


class MemberListResponse(BaseModel):
    data: list[MemberResponse]


class PermissionsResponse(BaseModel):
    role: str
    allowed_sections: list[str]
    allowed_pages: list[str] | None = None
    write_pages: list[str] | None = None
    is_platform_admin: bool = False
