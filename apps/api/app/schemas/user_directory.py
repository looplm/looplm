"""Pydantic schemas for the user directory (identities + groups)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class UserIdentityCreate(BaseModel):
    name: str
    user_ids: list[str] = Field(default_factory=list)


class UserIdentityUpdate(BaseModel):
    name: Optional[str] = None
    user_ids: Optional[list[str]] = None


class UserIdentityResponse(BaseModel):
    id: UUID
    name: str
    user_ids: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserIdentityListResponse(BaseModel):
    data: list[UserIdentityResponse]
    total: int


class UserGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    identity_ids: list[UUID] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list)


class UserGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    identity_ids: Optional[list[UUID]] = None
    user_ids: Optional[list[str]] = None


class UserGroupResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    identity_ids: list[UUID]
    user_ids: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserGroupListResponse(BaseModel):
    data: list[UserGroupResponse]
    total: int
