"""Pydantic schemas for the first-party tracing ingest endpoint.

Public field names follow OpenTelemetry GenAI conventions where it's free
(``model``, ``input_tokens``/``output_tokens``), so a future OTLP adapter is
additive. The router maps these to the internal normalized-trace dict consumed
by ``trace_persistence.persist_normalized_trace``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SpanTypeLiteral = Literal["llm", "tool", "retriever", "chain", "agent"]
TraceStatusLiteral = Literal["success", "failure", "degraded"]


class IngestSpan(BaseModel):
    external_id: Optional[str] = Field(None, max_length=512)
    name: Optional[str] = Field(None, max_length=512)
    type: Optional[SpanTypeLiteral] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    model: Optional[str] = Field(None, max_length=255)
    input_tokens: Optional[int] = Field(None, ge=0)
    output_tokens: Optional[int] = Field(None, ge=0)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = Field(None, ge=0)
    status: Optional[str] = Field(None, max_length=64)
    error_message: Optional[str] = None
    parent_external_id: Optional[str] = Field(None, max_length=512)


class IngestTrace(BaseModel):
    external_id: Optional[str] = Field(None, max_length=512)
    name: Optional[str] = Field(None, max_length=512)
    input: Optional[Any] = None
    output: Optional[Any] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = Field(None, ge=0)
    status: TraceStatusLiteral = "success"
    error_message: Optional[str] = None
    thread_id: Optional[str] = Field(None, max_length=512)
    user_id: Optional[str] = Field(None, max_length=512)
    run_type: Optional[str] = Field(None, max_length=64)
    spans: list[IngestSpan] = Field(default_factory=list)


class IngestRequest(BaseModel):
    traces: list[IngestTrace] = Field(..., min_length=1)


class IngestResponse(BaseModel):
    accepted: int
    trace_ids: list[str]
