"""Pydantic schemas for Code Agent — eval-driven code suggestions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Agent structured output schema ────────────────────────────

class AgentCodeSuggestion(BaseModel):
    """Single suggestion returned by the Claude agent."""

    type: str = Field(description="prompt_change, code_fix, config_change, or architecture_change")
    title: str
    description: str
    file_path: str | None = Field(
        default=None, description="Source file path (null when no repo configured)"
    )
    line_start: int | None = None
    line_end: int | None = None
    diff: dict | None = Field(
        default=None, description="Code diff with 'before' and 'after' keys"
    )
    impact: str = Field(description="high, medium, or low")
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    related_test_ids: list[str] = Field(default_factory=list)


class AgentAnalysisOutput(BaseModel):
    """Structured output schema for the Claude agent."""

    failure_summary: str
    suggestions: list[AgentCodeSuggestion]
    files_analyzed: list[str] = Field(default_factory=list)


# ── Request schemas ───────────────────────────────────────────

class TriggerOpenCodeRequest(BaseModel):
    extra_context: str = ""
    file_patterns: list[str] | None = None
    analysis_mode: str = Field(default="detailed", description="'quick' or 'detailed'")


class CodeSuggestionStatusUpdate(BaseModel):
    status: str = Field(description="applied or dismissed")


# ── Response schemas ──────────────────────────────────────────

class CodeSuggestionItem(BaseModel):
    id: UUID
    type: str
    title: str
    description: str | None = None
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    diff: dict | None = None
    impact: str | None = None
    confidence: float | None = None
    reasoning: str | None = None
    related_test_ids: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class OpenCodeAnalysisResponse(BaseModel):
    id: UUID
    eval_run_id: UUID
    status: str
    error: str | None = None
    files_analyzed: list[str] = Field(default_factory=list)
    failure_summary: str | None = None
    suggestion_count: int = 0
    suggestions: list[CodeSuggestionItem] = Field(default_factory=list)
    total_cost_usd: float | None = None
    num_turns: int | None = None
    analysis_mode: str | None = None
    progress_message: str | None = None
    progress_log: list[dict] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}
