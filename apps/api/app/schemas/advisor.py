"""Pydantic schemas for architecture advisor."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SuggestionCategory(str, Enum):
    time_to_value = "time_to_value"
    output_quality = "output_quality"
    architecture = "architecture"


class ImpactLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Suggestion(BaseModel):
    title: str
    description: str
    category: SuggestionCategory
    impact: ImpactLevel
    confidence: float = Field(ge=0, le=1)
    reasoning: str = ""


class AdvisorResponse(BaseModel):
    integration_id: str
    suggestions: list[Suggestion] = Field(default_factory=list)
    analyzed_at: datetime | None = None


class AdvisorAnalyzeRequest(BaseModel):
    extra_context: str = ""
    # When true, run the repo-aware agentic path (async, requires a connected
    # GitHub repo). When false/absent, the synchronous graph-only path runs.
    use_repo: bool = False


class AdvisorAgentSuggestion(BaseModel):
    """Suggestion emitted by the repo-aware agent (Pydantic AI output item)."""

    title: str
    description: str
    category: SuggestionCategory
    impact: ImpactLevel
    confidence: float = Field(ge=0, le=1)
    reasoning: str = ""


class AdvisorAgentOutput(BaseModel):
    """Structured output type the repo-aware advisor agent must return."""

    suggestions: list[AdvisorAgentSuggestion] = Field(default_factory=list)
    files_analyzed: list[str] = Field(default_factory=list)


class AdvisorRunResponse(BaseModel):
    """Poll shape for an async repo-aware advisor run (superset of AdvisorResponse)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    integration_id: str
    status: str
    suggestions: list[Suggestion] = Field(default_factory=list)
    error: str | None = None
    files_analyzed: list[str] = Field(default_factory=list)
    num_turns: int | None = None
    total_cost_usd: float | None = None
    repo_used: bool = False
    progress_message: str | None = None
    progress_log: list[dict] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    analyzed_at: datetime | None = None
