"""Pydantic schemas for chunk/metadata quality runs.

The ``results`` blob is the engine's ``ChunkQualityReport.to_dict()`` and is
validated loosely (like ``GapRunResponse.results``) — its shape lives in
:mod:`app.index_providers.chunk_quality`, not here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ChunkQualityRunRequest(BaseModel):
    provider_id: UUID
    # Target number of chunks to sample (the actual count may be lower for small indexes).
    sample_size: int = Field(default=8000, ge=100, le=50000)


class ChunkQualityRunCreateResponse(BaseModel):
    run_id: UUID
    status: str


class ChunkQualityRunSummary(BaseModel):
    id: UUID
    provider_id: UUID
    status: str
    sample_size: int
    total_docs: int
    processed: int
    score: Optional[int] = None
    critical: int = 0
    warn: int = 0
    info: int = 0
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class ChunkQualityRunSummaryListResponse(BaseModel):
    data: list[ChunkQualityRunSummary]


class ChunkQualityRunResponse(BaseModel):
    id: UUID
    provider_id: UUID
    status: str
    sample_size: int
    total_docs: int
    processed: int
    error: Optional[str] = None
    results: Optional[dict[str, Any]] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
