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
    total: int
    positive: int
    negative: int
    positive_rate: float
    no_feedback_traces: int


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
