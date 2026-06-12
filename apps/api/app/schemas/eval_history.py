"""Pydantic schemas for the cross-run test case history endpoint."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TestCaseTrendPoint(BaseModel):
    """One run's outcome for a test case, newest-first in the trend list."""
    run_id: UUID
    created_at: datetime
    passed: bool
    is_rerun: bool = False


class TestCaseHistoryItem(BaseModel):
    test_id: str
    dataset_id: UUID | None = None
    dataset_name: str | None = None
    case_status: str | None = None  # active | needs_work; None when the test case no longer exists
    exists: bool = True
    runs_participated: int
    pass_count: int
    fail_count: int
    pass_rate: float
    dominant_failure_pattern: str | None = None
    dominant_failure_pattern_count: int = 0
    dominant_root_cause: str | None = None
    dominant_root_cause_count: int = 0
    unclassified_failures: int = 0
    last_failed_at: datetime | None = None
    last_failed_run_id: UUID | None = None
    trend: list[TestCaseTrendPoint] = Field(default_factory=list)


class TestCaseHistoryResponse(BaseModel):
    data: list[TestCaseHistoryItem]
    runs_considered: int
    oldest_run_at: datetime | None = None
