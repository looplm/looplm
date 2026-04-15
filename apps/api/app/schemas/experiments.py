"""Pydantic schemas for experiment endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ExperimentCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)


class ExperimentUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    variables: dict[str, str] | None = None


class ExperimentResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    variables: dict[str, str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExperimentListResponse(BaseModel):
    data: list[ExperimentResponse]
