"""Pydantic schemas for architecture advisor."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


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
