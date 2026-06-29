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


class TransferOwnership(BaseModel):
    new_owner_id: UUID


class RetrievalSourceSuggestion(BaseModel):
    kind: str  # "span" | "payload_key"
    value: str
    confidence: str  # "high" | "medium" | "low"
    reasoning: str | None = None


class RetrievalSourceCandidates(BaseModel):
    payload_keys: list[dict] = Field(default_factory=list)
    spans: list[dict] = Field(default_factory=list)


class RetrievalSourceDetection(BaseModel):
    suggestion: RetrievalSourceSuggestion | None = None
    candidates: RetrievalSourceCandidates


class EmbeddingTestResult(BaseModel):
    """Result of a live embedding-config test (does the embedding endpoint work?)."""

    ok: bool
    configured: bool
    model: str | None = None
    dimensions: int | None = None
    error: str | None = None
