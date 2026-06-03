"""Pydantic schemas for evaluation endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# --- Import schema (request body) ---

class GraderResult(BaseModel):
    pass_: bool = Field(alias="pass")
    reason: Optional[str] = None
    skipped: Optional[bool] = False
    details: Optional[dict[str, Any]] = None

    model_config = {"populate_by_name": True}


class EvalResultImport(BaseModel):
    test_id: str
    pass_: bool = Field(alias="pass")
    reason: Optional[str] = None
    input: Optional[str] = None
    output: Optional[str] = None
    expected_output: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    graders: dict[str, GraderResult] = Field(default_factory=dict)
    scores: dict[str, float] = Field(default_factory=dict)
    turns_to_pass: Optional[int] = None

    model_config = {"populate_by_name": True}


class EvalImportRequest(BaseModel):
    name: str
    source: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    results: list[EvalResultImport]


# --- Response schemas ---

class GraderSummaryItem(BaseModel):
    total: int
    passed: int
    failed: int
    skipped: int
    pass_rate: float


class ScoreSummaryItem(BaseModel):
    count: int
    avg: float
    min: float
    max: float


class EvalRunListItem(BaseModel):
    id: UUID
    name: str
    source: Optional[str] = None
    tags: list[str]
    total: int
    passed: int
    failed: int
    pass_rate: float
    grader_summary: dict[str, GraderSummaryItem]
    score_summary: dict[str, ScoreSummaryItem]
    metadata: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginationInfo(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


class EvalRunListResponse(BaseModel):
    data: list[EvalRunListItem]
    pagination: PaginationInfo


class GraderResultSummary(BaseModel):
    """Trimmed grader result used in the list-of-results response (no `details`)."""
    pass_: bool = Field(alias="pass")
    reason: Optional[str] = None
    skipped: Optional[bool] = False

    model_config = {"populate_by_name": True}


class EvalResultSummary(BaseModel):
    """Lightweight row used by the eval-run detail table — no input/output/reason text."""
    id: UUID
    test_id: str
    pass_: bool = Field(alias="pass")
    tags: list[str]
    graders: dict[str, GraderResultSummary]
    turns_to_pass: Optional[int] = None
    turn_count: Optional[int] = None
    failure_pattern: Optional[str] = None
    grader_pattern: list[str] = Field(default_factory=list)
    root_cause: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class ClassifyFailuresResponse(BaseModel):
    """Response from POST /api/evals/{run_id}/classify-failures."""
    total: int
    passed: int
    failed: int
    pass_rate: float
    classified: int
    failure_pattern_summary: dict[str, int] = Field(default_factory=dict)


class EvalResultItem(BaseModel):
    id: UUID
    test_id: str
    pass_: bool = Field(alias="pass")
    reason: Optional[str] = None
    input: Optional[str] = None
    output: Optional[str] = None
    expected_output: Optional[str] = None
    tags: list[str]
    graders: dict[str, Any]
    scores: dict[str, float]
    metadata: dict[str, Any]
    turns_to_pass: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class EvalRunDetail(BaseModel):
    id: UUID
    name: str
    source: Optional[str] = None
    tags: list[str]
    total: int
    passed: int
    failed: int
    pass_rate: float
    grader_summary: dict[str, GraderSummaryItem]
    score_summary: dict[str, ScoreSummaryItem]
    metadata: dict[str, Any]
    created_at: datetime
    results: list[EvalResultSummary]

    model_config = {"from_attributes": True}


class EvalRunStats(BaseModel):
    total: int
    passed: int
    failed: int
    pass_rate: float
    grader_summary: dict[str, GraderSummaryItem]
    score_summary: dict[str, ScoreSummaryItem]


# --- Report schemas ---

class ReportTraceInfo(BaseModel):
    tool_calls_count: int = 0
    tools_used: list[str] = Field(default_factory=list)
    token_usage: Optional[dict[str, Any]] = None
    raw_response_excerpt: Optional[str] = None


class ReportGraderEntry(BaseModel):
    reason: Optional[str] = None


class ReportTestCaseDetail(BaseModel):
    test_id: str
    pass_: bool = Field(alias="pass")
    input: Optional[str] = None
    output: Optional[str] = None
    expected_output: Optional[str] = None
    failed_graders: dict[str, ReportGraderEntry] = Field(default_factory=dict)
    passed_graders: dict[str, ReportGraderEntry] = Field(default_factory=dict)
    skipped_graders: dict[str, ReportGraderEntry] = Field(default_factory=dict)
    scores: dict[str, float] = Field(default_factory=dict)
    trace: ReportTraceInfo = Field(default_factory=ReportTraceInfo)
    preconditions: Optional[dict[str, Any]] = None

    model_config = {"populate_by_name": True}


class ReportGraderFailure(BaseModel):
    fail_count: int = 0
    affects_pass: bool = False
    common_issues: list[str] = Field(default_factory=list)
    failed_test_ids: list[str] = Field(default_factory=list)


class ReportFailureAnalysis(BaseModel):
    by_grader: dict[str, ReportGraderFailure] = Field(default_factory=dict)
    by_test_case: list[ReportTestCaseDetail] = Field(default_factory=list)


class ReportSummary(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    grader_summary: dict[str, GraderSummaryItem] = Field(default_factory=dict)
    score_summary: dict[str, ScoreSummaryItem] = Field(default_factory=dict)


class ReportEvalRunInfo(BaseModel):
    id: str
    name: str
    created_at: Optional[str] = None
    source: Optional[str] = None


class EvalReportResponse(BaseModel):
    eval_run: ReportEvalRunInfo
    summary: ReportSummary
    failure_analysis: ReportFailureAnalysis
    recommendations: list[str] = Field(default_factory=list)


# --- Multi-run report schemas ---

class MultiRunReportRequest(BaseModel):
    run_ids: list[UUID] = Field(..., min_length=1, max_length=20)
    relevance_filter: list[str] | None = Field(
        None,
        description="Filter graders by relevance level (e.g. ['core', 'important']). None means include all.",
    )


class MultiRunReportResponse(BaseModel):
    id: Optional[UUID] = None
    markdown: str
    run_count: int
    total_tests: int


# --- Saved report schemas ---

class EvalReportListItem(BaseModel):
    id: UUID
    title: str
    report_type: str
    run_ids: list[str]
    run_count: int
    total_tests: int
    created_at: datetime

    model_config = {"from_attributes": True}


class EvalReportListResponse(BaseModel):
    data: list[EvalReportListItem]
    pagination: PaginationInfo


class EvalReportDetail(BaseModel):
    id: UUID
    title: str
    report_type: str
    markdown: str
    run_ids: list[str]
    run_count: int
    total_tests: int
    created_at: datetime

    model_config = {"from_attributes": True}
