"""Pydantic schemas for feedback endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class FeedbackScoreItem(BaseModel):
    id: UUID
    trace_id: Optional[UUID] = None
    external_trace_id: str
    score_name: str
    value: float
    data_type: str
    comment: Optional[str] = None
    scored_at: Optional[datetime] = None
    created_at: datetime
    # Joined trace fields
    trace_input: Optional[Any] = None
    trace_output: Optional[Any] = None
    trace_status: Optional[str] = None
    trace_start_time: Optional[datetime] = None
    trace_name: Optional[str] = None
    trace_metadata: dict[str, Any] = Field(default_factory=dict)
    # Joined eval result fields (from latest FeedbackEvalResult)
    eval_verdict: Optional[str] = None
    eval_reasoning: Optional[str] = None
    eval_confidence: Optional[float] = None

    model_config = {"from_attributes": True}


class FeedbackScoreDetail(FeedbackScoreItem):
    trace_metadata: dict[str, Any] = Field(default_factory=dict)
    trace_duration_ms: Optional[int] = None
    trace_error_message: Optional[str] = None


class PaginationInfo(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


class FeedbackListResponse(BaseModel):
    data: list[FeedbackScoreItem]
    pagination: PaginationInfo


class FeedbackTrend(BaseModel):
    date: str
    positive: int
    negative: int
    total: int


class GraderStats(BaseModel):
    name: str
    total: int
    passed: int
    failed: int
    pass_rate: float


class GraderTrend(BaseModel):
    date: str
    passed: int
    failed: int
    total: int


class FeedbackStatsResponse(BaseModel):
    total_feedback: int
    positive: int
    negative: int
    no_feedback_traces: int
    positive_rate: float
    trends: list[FeedbackTrend]
    grader_stats: list[GraderStats]
    grader_trends: dict[str, list[GraderTrend]] = {}


# --- Feedback Evaluation ---


class FeedbackEvaluateRequest(BaseModel):
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    environment: Optional[str] = None
    limit: int = Field(50, ge=1, le=200)
    reevaluate: bool = False


class FeedbackEvalItem(BaseModel):
    feedback_id: UUID
    trace_id: Optional[UUID] = None
    score_name: str
    value: float
    comment: Optional[str] = None
    trace_input_preview: Optional[str] = None
    verdict: str  # "suspicious" | "helpful" | "unhelpful"
    reasoning: str
    confidence: float  # 0.0 - 1.0


class FeedbackEvalSummary(BaseModel):
    total_count: int
    evaluated_count: int
    suspicious_count: int = 0
    helpful_count: int = 0
    unhelpful_count: int = 0
    verdict_counts: dict[str, int] = {}


class FeedbackEvaluateResponse(BaseModel):
    id: UUID
    status: str  # "pending" | "running" | "completed" | "failed"
    error: Optional[str] = None
    summary: FeedbackEvalSummary
    items: list[FeedbackEvalItem]
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# --- Feedback Evaluator Config ---


class FeedbackEvaluatorConfigResponse(BaseModel):
    id: UUID
    prompt: str
    verdicts: list[str]
    default_verdict: str
    model: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FeedbackEvaluatorConfigUpdate(BaseModel):
    prompt: Optional[str] = None
    verdicts: Optional[list[str]] = None
    default_verdict: Optional[str] = None
    model: Optional[str] = None


# --- Top Questions Analysis ---


class TopQuestionsRequest(BaseModel):
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    environment: Optional[str] = None
    limit: int = Field(200, ge=10, le=500)


class TopQuestionItem(BaseModel):
    question: str
    feedback_value: Optional[float] = None
    trace_id: Optional[UUID] = None


class TopQuestionTheme(BaseModel):
    rank: int
    theme: str
    count: int
    summary_question: str = ""
    all_questions: list[TopQuestionItem] = []
    feedback_sentiment: dict[str, int] = {}


class TopQuestionsResponse(BaseModel):
    id: UUID
    status: str  # "pending" | "running" | "completed" | "failed"
    error: Optional[str] = None
    total_questions: int = 0
    processed_questions: int = 0
    themes: list[TopQuestionTheme] = []
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# --- Suggestion Run ---


class SuggestionRunResponse(BaseModel):
    id: UUID
    status: str  # "pending" | "running" | "completed" | "failed"
    error: Optional[str] = None
    total: int = 0
    processed: int = 0
    count: int = 0
    suggestions: list[Any] = []
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
