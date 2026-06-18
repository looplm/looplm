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


class RagSource(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    score: Optional[float] = None
    score_scale: Optional[str] = None
    tool_name: Optional[str] = None
    content_preview: Optional[str] = None
    # Whether this found source made it into the final LLM context, and which
    # ``[N]`` citation marker it maps to. Exact when rde-gpt logs it; otherwise
    # inferred from the source order the agent passed to the grounding judge.
    selected: bool = False
    citation_index: Optional[int] = None
    # True when ``selected``/``citation_index`` were read from explicit span fields
    # rather than inferred — lets the UI distinguish certain from reconstructed.
    selection_exact: bool = False


class RagSearchFunnel(BaseModel):
    search_call_count: Optional[int] = None
    summary_pages: Optional[int] = None
    chunk_results: Optional[int] = None
    broadened: Optional[bool] = None
    has_results: Optional[bool] = None
    # Drop counts — only present once rde-gpt logs them on the search span.
    candidates_before_filter: Optional[int] = None
    dropped_by_relative_filter: Optional[int] = None
    dropped_by_absolute_floor: Optional[int] = None
    kept: Optional[int] = None


class RagJudgeCorrection(BaseModel):
    type: Optional[str] = None
    find: Optional[str] = None
    replacement: Optional[str] = None
    reason: Optional[str] = None


class RagJudge(BaseModel):
    passed: Optional[bool] = None
    corrections: list[RagJudgeCorrection] = Field(default_factory=list)


class RagCounts(BaseModel):
    found: int = 0
    used_in_context: int = 0
    cited: int = 0


class RagPipelineView(BaseModel):
    """Structured agentic-RAG pipeline derived from a trace's spans.

    ``available`` is False when no RAG spans were detected (e.g. a non-RAG trace),
    in which case the rest is empty and the UI falls back to the raw span tree.
    """

    available: bool = False
    queries: list[str] = Field(default_factory=list)
    query_complexity: Optional[str] = None
    search: Optional[RagSearchFunnel] = None
    sources: list[RagSource] = Field(default_factory=list)
    assembled_context: Optional[str] = None
    answer: Optional[str] = None
    answer_tokens_in: Optional[int] = None
    answer_tokens_out: Optional[int] = None
    answer_model: Optional[str] = None
    judge: Optional[RagJudge] = None
    counts: RagCounts = Field(default_factory=RagCounts)


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
    # Keyset pagination (set only when the request used a cursor). In that mode
    # `total`/`total_pages` are not computed (returned as 0) — use `has_more`.
    next_cursor: Optional[str] = None
    has_more: Optional[bool] = None


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
