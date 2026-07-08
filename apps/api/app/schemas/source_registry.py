"""Pydantic schemas for the wanted-status source registry + gap runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SourceExpectationResponse(BaseModel):
    id: UUID
    provider_id: UUID
    name: str
    html_url: Optional[str] = None
    pdf_url: Optional[str] = None
    adapter_tag: Optional[str] = None
    typ: Optional[str] = None
    sparte: Optional[str] = None
    thema: Optional[str] = None
    publisher: Optional[str] = None
    hierarchie: Optional[str] = None
    update_frequency: Optional[str] = None
    comment: Optional[str] = None
    ack_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SourceExpectationListResponse(BaseModel):
    data: list[SourceExpectationResponse]


class SourceExpectationCreate(BaseModel):
    provider_id: UUID
    name: str = Field(..., min_length=1, max_length=512)
    html_url: Optional[str] = Field(None, max_length=2048)
    pdf_url: Optional[str] = Field(None, max_length=2048)
    adapter_tag: Optional[str] = Field(None, max_length=64)
    typ: Optional[str] = None
    sparte: Optional[str] = None
    thema: Optional[str] = None
    publisher: Optional[str] = None
    hierarchie: Optional[str] = None
    update_frequency: Optional[str] = None
    comment: Optional[str] = None


class SourceExpectationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=512)
    html_url: Optional[str] = Field(None, max_length=2048)
    pdf_url: Optional[str] = Field(None, max_length=2048)
    adapter_tag: Optional[str] = Field(None, max_length=64)
    typ: Optional[str] = None
    sparte: Optional[str] = None
    thema: Optional[str] = None
    publisher: Optional[str] = None
    hierarchie: Optional[str] = None
    update_frequency: Optional[str] = None
    comment: Optional[str] = None
    # Explicit empty string clears the ack (None means "not provided").
    ack_note: Optional[str] = None


class CsvImportRequest(BaseModel):
    provider_id: UUID
    # Raw CSV text; the client decodes the file (incl. legacy encodings).
    csv_text: str = Field(..., min_length=1)
    # Replace = delete expectations for this provider that the CSV no longer contains.
    replace: bool = False


class CsvImportResponse(BaseModel):
    created: int
    updated: int
    deleted: int
    skipped_rows: int
    total: int
    warnings: list[str] = Field(default_factory=list)


class GapRunRequest(BaseModel):
    provider_id: UUID


class GapRunSummary(BaseModel):
    id: UUID
    provider_id: UUID
    status: str
    total: int
    processed: int
    covered: int = 0
    missing: int = 0
    review: int = 0
    acked: int = 0
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class GapRunSummaryListResponse(BaseModel):
    data: list[GapRunSummary]


class GapRunResponse(BaseModel):
    id: UUID
    provider_id: UUID
    status: str
    total: int
    processed: int
    error: Optional[str] = None
    results: Optional[dict[str, Any]] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class GapRunCreateResponse(BaseModel):
    run_id: UUID
    status: str


# ── Source chunk review ──────────────────────────────────────────────────────


class SourceChunk(BaseModel):
    id: str
    index: int
    ordinal: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    text: Optional[str] = None


class SourceChunksResponse(BaseModel):
    expectation_id: UUID
    name: str
    # How the source was located in the index: "url" hash hit, "title" search, or
    # "none" when nothing matched.
    resolution: str
    resolved: bool
    kind: Optional[str] = None
    matched_title: Optional[str] = None
    matched_url: Optional[str] = None
    chunk_count: int
    ordinal_available: bool
    # Holes and repeats in the chunk-ordinal (e.g. chunk_index) sequence — the
    # completeness signals surfaced while paging through the chunks.
    missing_ordinals: list[int] = Field(default_factory=list)
    duplicate_ordinals: list[int] = Field(default_factory=list)
    gaps_truncated: bool = False
    chunks: list[SourceChunk] = Field(default_factory=list)
