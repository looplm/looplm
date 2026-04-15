"""Pydantic schemas for projects."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    settings: dict | None = None


class ProjectResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    settings: dict
    created_at: datetime
    updated_at: datetime
    role: str = "owner"

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    data: list[ProjectResponse]
