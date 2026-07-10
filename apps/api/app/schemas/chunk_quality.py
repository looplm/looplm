"""Pydantic schemas for chunk/metadata quality runs.

The ``results`` blob is the engine's ``ChunkQualityReport.to_dict()`` and is
validated loosely (like ``GapRunResponse.results``) — its shape lives in
:mod:`app.index_providers.chunk_quality`, not here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class StandalonePassConfig(BaseModel):
    """LLM judge: is each sampled chunk interpretable without its surroundings?"""

    enabled: bool = False
    sample_size: int = Field(default=200, ge=20, le=500)


class CohesionPassConfig(BaseModel):
    """Embedding spread of a chunk's sentences — flags multi-topic chunks."""

    enabled: bool = False
    sample_size: int = Field(default=150, ge=20, le=400)
    max_sentences: int = Field(default=30, ge=5, le=50)


class RetrievalFrequencyPassConfig(BaseModel):
    """How often each chunk shows up in retrieval — dead and hot tails."""

    enabled: bool = False
    source: Literal["traces", "probe"] = "traces"
    window_days: int = Field(default=30, ge=1, le=365)
    dataset_id: Optional[UUID] = None  # probe source only
    max_queries: int = Field(default=100, ge=10, le=300)


class ClaimBoundaryPassConfig(BaseModel):
    """Atomic claims of gold answers grounded in one chunk vs split across chunks."""

    enabled: bool = False
    dataset_id: Optional[UUID] = None
    max_cases: int = Field(default=50, ge=5, le=200)


class ChunkQualityPasses(BaseModel):
    standalone: StandalonePassConfig = StandalonePassConfig()
    cohesion: CohesionPassConfig = CohesionPassConfig()
    retrieval_frequency: RetrievalFrequencyPassConfig = RetrievalFrequencyPassConfig()
    claim_boundary: ClaimBoundaryPassConfig = ClaimBoundaryPassConfig()


class ChunkQualityRunConfig(BaseModel):
    """Opt-in extended passes. The base families always run and cost nothing."""

    passes: ChunkQualityPasses = ChunkQualityPasses()


class ChunkQualityRunRequest(BaseModel):
    provider_id: UUID
    # Target number of chunks to sample (the actual count may be lower for small indexes).
    sample_size: int = Field(default=8000, ge=100, le=50000)
    config: Optional[ChunkQualityRunConfig] = None


class ChunkQualityRunCreateResponse(BaseModel):
    run_id: UUID
    status: str


class ChunkQualityRunSummary(BaseModel):
    id: UUID
    provider_id: UUID
    status: str
    stage: Optional[str] = None
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
    # Per-family headline metrics lifted out of results, for cross-run trends
    # (e.g. standalone_dependent_pct, boundary_bad_end_pct, dead_pct).
    headline: dict[str, Optional[float]] = Field(default_factory=dict)
    config: Optional[dict[str, Any]] = None


class ChunkQualityRunSummaryListResponse(BaseModel):
    data: list[ChunkQualityRunSummary]


class ChunkQualityRunResponse(BaseModel):
    id: UUID
    provider_id: UUID
    status: str
    stage: Optional[str] = None
    sample_size: int
    total_docs: int
    processed: int
    error: Optional[str] = None
    results: Optional[dict[str, Any]] = None
    config: Optional[dict[str, Any]] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
