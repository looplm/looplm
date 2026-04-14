"""Pydantic models for the Langfuse connector."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl


class LangfuseConfig(BaseModel):
    """Configuration required to connect to a Langfuse instance."""

    base_url: HttpUrl = Field(
        default="https://cloud.langfuse.com",
        description="Base URL of the Langfuse instance (cloud or self-hosted).",
    )
    public_key: str = Field(..., description="Langfuse public API key (used as Basic Auth username).")
    secret_key: str = Field(..., description="Langfuse secret API key (used as Basic Auth password).")


class NormalizedSpan(BaseModel):
    """A single observation/span within a trace, normalized to LoopLM schema."""

    id: str
    parent_id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = Field(None, description="Observation type: GENERATION, SPAN, EVENT.")
    input: Optional[Any] = None
    output: Optional[Any] = None
    model: Optional[str] = None
    tokens: Dict[str, Optional[int]] = Field(
        default_factory=dict,
        description="Token usage: keys may include 'input', 'output', 'total'.",
    )
    duration: Optional[float] = Field(None, description="Duration in seconds.")
    status: Optional[str] = Field(None, description="Observation level: DEFAULT, DEBUG, WARNING, ERROR.")
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    metadata: Optional[Any] = None


class NormalizedScore(BaseModel):
    """A score from Langfuse, normalized to LoopLM schema."""

    id: str
    trace_id: str
    name: str  # "user-feedback", "grader_faithfulness", etc.
    value: float  # 0 or 1 for BOOLEAN, 0-1 for numeric
    data_type: str = "BOOLEAN"  # "BOOLEAN", "NUMERIC"
    comment: Optional[str] = None
    created_at: Optional[datetime] = None


class NormalizedTrace(BaseModel):
    """A trace normalized to LoopLM's unified schema."""

    id: str
    name: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    status: str = Field(
        default="unknown",
        description="Inferred status: success, failure, degraded, or unknown.",
    )
    spans: List[NormalizedSpan] = Field(default_factory=list)
    metadata: Optional[Any] = None
    tags: List[str] = Field(default_factory=list)
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    release: Optional[str] = None
    version: Optional[str] = None
    latency: Optional[float] = Field(None, description="Total trace latency in seconds.")
    total_cost: Optional[float] = Field(None, description="Total cost in USD.")
    timestamp: Optional[datetime] = None
    created_at: Optional[datetime] = None
