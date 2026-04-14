"""Pydantic schemas for traces endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SpanResponse(BaseModel):
    id: UUID
    parent_span_id: Optional[UUID] = None
    external_id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    model: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    duration_ms: Optional[int] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    children: list[SpanResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TraceListItem(BaseModel):
    id: UUID
    integration_id: UUID
    external_id: str
    name: Optional[str] = None
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    parent_trace_id: Optional[UUID] = None
    root_trace_id: Optional[UUID] = None
    run_type: Optional[str] = None
    input: Optional[Any] = None
    status: Optional[str] = None
    duration_ms: Optional[int] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    child_run_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class TraceDetail(BaseModel):
    id: UUID
    integration_id: UUID
    external_id: str
    name: Optional[str] = None
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    parent_trace_id: Optional[UUID] = None
    root_trace_id: Optional[UUID] = None
    run_type: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: Optional[str] = None
    duration_ms: Optional[int] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    spans: list[SpanResponse] = Field(default_factory=list)
    child_run_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginationInfo(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


class TraceListResponse(BaseModel):
    data: list[TraceListItem]
    pagination: PaginationInfo


class ThreadSummary(BaseModel):
    thread_id: str
    trace_count: int
    first_time: datetime
    last_time: datetime
    total_duration_ms: Optional[int] = None
    has_failures: bool
    traces: list[TraceListItem] = Field(default_factory=list)


class ThreadOrderItem(BaseModel):
    type: str  # "thread" or "trace"
    id: str  # thread_id or trace id


class ThreadListResponse(BaseModel):
    data: list[ThreadSummary]
    standalone_traces: list[TraceListItem]
    order: list[ThreadOrderItem]
    pagination: PaginationInfo


class TraceTreeNode(BaseModel):
    id: UUID
    name: Optional[str] = None
    run_type: Optional[str] = None
    status: Optional[str] = None
    duration_ms: Optional[int] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    children: list["TraceTreeNode"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TraceChildrenResponse(BaseModel):
    root: TraceTreeNode
    children: list[TraceTreeNode] = Field(default_factory=list)
    total_children: int = 0


class AnalysisResponse(BaseModel):
    id: UUID
    trace_id: UUID
    failure_type: Optional[str] = None
    root_cause: Optional[str] = None
    confidence: Optional[float] = None
    applied: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class FixSuggestionResponse(BaseModel):
    id: UUID
    type: str
    title: str
    description: Optional[str] = None
    diff: Optional[Any] = None
    status: str = "pending"
    created_at: datetime

    model_config = {"from_attributes": True}


class TraceAnalysisResponse(BaseModel):
    analysis: AnalysisResponse
    fix_suggestions: list[FixSuggestionResponse]


class AnalyzeResponse(BaseModel):
    message: str = "Analysis started"
    trace_id: UUID
    analysis_id: UUID


class TraceImportItem(BaseModel):
    name: str | None = None
    input: dict | list | str | None = None
    output: dict | list | str | None = None
    status: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    metadata: dict | None = None
    thread_id: str | None = None


class TraceImportRequest(BaseModel):
    traces: list[TraceImportItem]
    filename: str = "import.json"
