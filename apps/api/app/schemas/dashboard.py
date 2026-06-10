"""Pydantic schemas for dashboard endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class TopFailure(BaseModel):
    failure_type: str
    count: int
    percentage: float
    example_trace_id: Optional[UUID] = None


class TrendPoint(BaseModel):
    date: str
    total: int
    failures: int
    failure_rate: float
    unique_users: int
    unique_threads: int
    feedback_positive: int
    feedback_negative: int
    traces_with_feedback: int


class FixesStats(BaseModel):
    suggested: int
    applied: int
    dismissed: int
    pending: int


class DashboardTotals(BaseModel):
    traces: int
    failures: int
    degraded: int
    success: int
    failure_rate: float
    unique_users: int
    unique_threads: int


class FeedbackSummary(BaseModel):
    total: int            # feedback submissions (a trace can have several)
    positive: int
    negative: int
    positive_rate: float
    traces_with_feedback: int  # distinct traces with >=1 submission; + no_feedback_traces = total traces
    no_feedback_traces: int


class LatencyPercentiles(BaseModel):
    """Trace duration distribution — tails matter more than the average."""

    count: int
    p50_ms: Optional[int] = None
    p95_ms: Optional[int] = None
    p99_ms: Optional[int] = None


class ThreadMetrics(BaseModel):
    """Conversation-level signals derived from grouping traces by thread_id."""

    total_threads: int
    multi_turn_threads: int
    multi_turn_rate: float
    avg_thread_length: float
    p95_thread_length: int
    retry_rate: float


class RegressionFlag(BaseModel):
    """A metric that got materially worse vs the immediately-preceding window."""

    metric: str       # "failure_rate" | "latency_p95"
    label: str        # human-readable
    current: float
    previous: float
    change_pct: float  # relative change vs previous (e.g. 0.4 == +40%)
    regressed: bool


class DashboardPeriod(BaseModel):
    start: datetime
    end: datetime


class DashboardStatsResponse(BaseModel):
    period: DashboardPeriod
    totals: DashboardTotals
    top_failures: list[TopFailure]
    trends: list[TrendPoint]
    fixes: FixesStats
    feedback: FeedbackSummary
    latency: LatencyPercentiles
    threads: ThreadMetrics
    regressions: list[RegressionFlag]
