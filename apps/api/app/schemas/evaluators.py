"""Pydantic schemas for evaluator endpoints."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EvaluatorSource(str, Enum):
    custom = "custom"
    ragas = "ragas"
    langfuse = "langfuse"
    discovered = "discovered"


class EvaluatorCategory(str, Enum):
    retrieval = "retrieval"
    generation = "generation"


class EvaluatorCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    type: str  # llm_judge / deterministic / hybrid
    description: Optional[str] = None
    relevance: str = "important"
    affects_pass: bool = False
    config: dict[str, Any] = Field(default_factory=dict)
    source: EvaluatorSource = EvaluatorSource.custom
    # None → derive from the evaluator's name / check_type (see default_evaluator_category).
    category: Optional[EvaluatorCategory] = None


class EvaluatorImport(BaseModel):
    evaluators: list[EvaluatorCreate]


class EvaluatorImportResponse(BaseModel):
    created: int
    skipped: int
    total: int
    data: list[EvaluatorResponse]


class EvaluatorUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    relevance: Optional[str] = None
    affects_pass: Optional[bool] = None
    config: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    source: Optional[EvaluatorSource] = None
    category: Optional[EvaluatorCategory] = None


class EvaluatorResponse(BaseModel):
    id: UUID
    name: str
    display_name: Optional[str] = None
    type: str
    description: Optional[str] = None
    relevance: str
    affects_pass: bool
    config: dict[str, Any]
    source: Optional[str] = None
    category: str = "generation"
    enabled: bool
    total_evaluations: int = 0
    pass_rate: Optional[float] = None
    last_seen_at: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EvaluatorListResponse(BaseModel):
    data: list[EvaluatorResponse]
    total: int
