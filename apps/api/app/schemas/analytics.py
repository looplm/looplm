"""Pydantic schemas for the Analytics page endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# --- Request-type clustering ---


class RequestClustersRequest(BaseModel):
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    environment: Optional[str] = None
    include_user_ids: Optional[list[str]] = None
    exclude_user_ids: Optional[list[str]] = None
    limit: int = Field(300, ge=10, le=1000)


class RequestOutcome(BaseModel):
    success: int = 0
    degraded: int = 0
    failure: int = 0
    fb_positive: int = 0
    fb_negative: int = 0


class RequestClusterTheme(BaseModel):
    rank: int
    theme: str
    count: int
    summary_question: str = ""
    trace_ids: list[str] = []
    outcome: RequestOutcome = Field(default_factory=RequestOutcome)


class RequestClustersResponse(BaseModel):
    id: UUID
    status: str  # "pending" | "running" | "completed" | "failed" | "cancelled"
    error: Optional[str] = None
    total_requests: int = 0
    processed_requests: int = 0
    themes: list[RequestClusterTheme] = []
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# --- Data retrieval insights ---


class RetrievalSource(BaseModel):
    url: str
    domain: str
    label: str
    count: int


class RetrievalActivityPoint(BaseModel):
    date: str
    count: int


class RetrievalActivityResponse(BaseModel):
    """Retrieval coverage + reach, with a daily volume sparkline.

    ``coverage`` is the share of requests that triggered a retrieval at all
    (ungrounded answers are the failure mode worth surfacing); ``avg_sources_per_request``
    is how many distinct sources a retrieving request pulls on average.
    """

    requests_total: int
    requests_with_retrieval: int
    coverage: float  # 0..1
    avg_sources_per_request: float
    daily: list[RetrievalActivityPoint]


class SpanNameCount(BaseModel):
    """A distinct span name and how often it occurs — feeds the retrieval
    span-name picker so the user can point the retrieval panels at the right step."""

    name: str
    count: int
