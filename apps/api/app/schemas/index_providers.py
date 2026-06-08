"""Pydantic schemas for index-provider + coverage endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# Only azure_search is implemented; the rest are reserved enum values.
_SUPPORTED_PROVIDER_TYPES = "azure_search"


class IndexProviderCreate(BaseModel):
    type: str = Field(..., pattern=f"^({_SUPPORTED_PROVIDER_TYPES})$")
    name: str = Field(..., max_length=255)
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None  # endpoint URL
    config: dict[str, Any] = Field(default_factory=dict)


class IndexProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    config: Optional[dict[str, Any]] = None


class IndexProviderResponse(BaseModel):
    id: UUID
    type: str
    name: str
    base_url: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IndexProviderListResponse(BaseModel):
    data: list[IndexProviderResponse]


class TestConnectionResponse(BaseModel):
    ok: bool
    document_count: Optional[int] = None
    error: Optional[str] = None


class PartitionKeyResponse(BaseModel):
    key: str
    label: str
    multivalued: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class PartitionKeyListResponse(BaseModel):
    data: list[PartitionKeyResponse]


class AnalyzeRequest(BaseModel):
    provider_id: UUID
    partition_key: str = Field(..., max_length=255)
    dataset_ids: Optional[list[UUID]] = None  # null = all datasets in project
    suggest: bool = False
    min_covering_cases: int = Field(1, ge=1)
    sample_n: int = Field(8, ge=1, le=50)
    max_questions_per_gap: int = Field(3, ge=1, le=10)
    max_gaps_to_suggest: int = Field(15, ge=1, le=100)


class CoverageEvalSuggestion(BaseModel):
    """An LLM-drafted eval question targeting one uncovered partition value."""

    partition_value: str
    prompt: str
    acceptance_criteria: str
    tag_filter: list[str] = Field(default_factory=list)
    team_filter: list[str] = Field(default_factory=list)
    expected_source_types: list[str] = Field(default_factory=list)
    context_filters: dict[str, str] = Field(default_factory=dict)


class CoverageRunResponse(BaseModel):
    id: UUID
    provider_id: UUID
    status: str
    error: Optional[str] = None
    partition_key: str
    dataset_ids: Optional[list[UUID]] = None
    suggest: bool = False
    min_covering_cases: int = 1
    total: int = 0
    processed: int = 0
    results: Optional[dict[str, Any]] = None
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_row(cls, run: Any) -> "CoverageRunResponse":
        return cls(
            id=run.id,
            provider_id=run.provider_id,
            status=run.status,
            error=run.error,
            partition_key=run.partition_key,
            dataset_ids=run.dataset_ids,
            suggest=str(run.suggest).lower() == "true",
            min_covering_cases=run.min_covering_cases,
            total=run.total,
            processed=run.processed,
            results=run.results,
            suggestions=run.suggestions or [],
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
        )


class CoverageRunListResponse(BaseModel):
    data: list[CoverageRunResponse]


class AnalyzeResponse(BaseModel):
    run_id: UUID
    status: str = "pending"
