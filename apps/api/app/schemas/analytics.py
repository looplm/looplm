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
    # The filter window this snapshot was computed over, so the UI can flag when
    # the live filter bar has drifted from the displayed analysis.
    filter_from_date: Optional[datetime] = None
    filter_to_date: Optional[datetime] = None
    filter_environment: Optional[str] = None


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


# --- Multi-hop retrieval ---


class MultiHopDefinition(BaseModel):
    """One way of calling a request "multi-hop", with its rate over the window.

    ``total`` is the *observable* denominator (requests where the signal could be
    measured at all), so a rate isn't diluted by traces that never carried the
    signal. ``rate`` is ``multi_hop / total`` (0..1), or None when nothing was
    observable.
    """

    key: str  # "complexity" | "drill_down" | "expansion" | "search_calls"
    label: str
    description: str
    multi_hop: int
    total: int
    rate: Optional[float] = None


class ComplexityBucket(BaseModel):
    """Count of requests at one logged query-complexity level."""

    level: str  # "simple" | "moderate" | "complex" | "unclassified"
    count: int


class HistogramBin(BaseModel):
    """One bar of a per-request distribution. ``value`` is the (tail-capped)
    count; ``label`` renders it (e.g. ``"5+"`` for the capped upper bin)."""

    value: int
    count: int
    label: str


class MultiHopResponse(BaseModel):
    """How many requests took more than one retrieval hop, by each definition.

    Derived on read from already-synced trace metadata (``queryComplexity``,
    ``expandedQueryCount``) plus the search span's funnel output
    (``searchCallCount``, ``summaryPages``) — no schema change or re-sync.
    """

    requests_total: int
    requests_analyzed: int  # requests carrying at least one observable signal
    definitions: list[MultiHopDefinition]
    complexity: list[ComplexityBucket]
    queries_per_request: list[HistogramBin]
    search_calls_per_request: list[HistogramBin]
    avg_queries_per_request: Optional[float] = None
    avg_search_calls_per_request: Optional[float] = None
