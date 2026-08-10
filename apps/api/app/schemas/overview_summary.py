"""Response schemas for GET /api/overview/summary."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

from app.schemas.overview_common import Delta, OverviewPeriod

# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


class FeedbackBucketPoint(BaseModel):
    bucket: str
    total: int
    positive: int
    negative: int
    traces_with_feedback: int
    positive_rate: float


class FeedbackTotals(BaseModel):
    total: int
    positive: int
    negative: int
    positive_rate: float
    traces_with_feedback: int


class FeedbackOverview(BaseModel):
    """End-user thumbs (``score_name == 'user-feedback'``) over time.

    Bucketed on the *trace's* ``start_time``, not the score's ``scored_at``, so these
    counts line up with the volume numbers in the adoption section for the same bucket.
    Same choice the dashboard already makes.
    """

    points: list[FeedbackBucketPoint]
    totals: FeedbackTotals


# ---------------------------------------------------------------------------
# Adoption / usage growth
# ---------------------------------------------------------------------------


class AdoptionBucketPoint(BaseModel):
    bucket: str
    active_users: int
    new_users: int
    returning_users: int
    cumulative_users: int
    traces: int
    # Traces carrying a user_id. The denominator for per-user averages; anonymous
    # traffic has no user to divide by.
    traces_attributed: int
    threads: int
    avg_traces_per_active_user: float
    # Trailing 1/7/30-day distinct users at this bucket's end. None when the activity
    # matrix was too large to roll (see AdoptionOverview.rolling_available).
    dau: Optional[int] = None
    wau: Optional[int] = None
    mau: Optional[int] = None
    stickiness: Optional[float] = None


class AdoptionTotals(BaseModel):
    active_users: int
    new_users: int
    returning_users: int
    # Distinct users who have ever appeared, up to the end of the window.
    cumulative_users: int
    traces: int
    traces_attributed: int
    threads: int
    avg_traces_per_active_user: float
    dau: Optional[int] = None
    wau: Optional[int] = None
    mau: Optional[int] = None
    stickiness: Optional[float] = None


class AdoptionGrowth(BaseModel):
    """Period-over-period change for the volume metrics."""

    traces: Delta
    threads: Delta
    active_users: Delta
    avg_traces_per_active_user: Delta


class AdoptionOverview(BaseModel):
    points: list[AdoptionBucketPoint]
    totals: AdoptionTotals
    growth: AdoptionGrowth
    # False when the user-day activity matrix exceeded its guard, in which case the
    # DAU/WAU/MAU fields are null rather than wrong.
    rolling_available: bool = True


# ---------------------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------------------


class EvalBucketPoint(BaseModel):
    bucket: str
    run_count: int
    cases: int
    passed: int
    # Case-weighted: sum(passed)/sum(total) across the runs in this bucket. None when
    # the bucket has no run with graded cases, which the UI renders as a gap in the
    # line rather than a drop to zero.
    pass_rate: Optional[float] = None
    # Mean of per-run pass rates, so a 5-case run and a 500-case run are comparable.
    unweighted_pass_rate: Optional[float] = None


class EvalProgress(BaseModel):
    """Dataset coverage: how much of the test suite has ever been evaluated.

    All-time on purpose. Scoping this to the selected window would make the number
    shrink whenever the user narrows the date range, which reads as a regression.
    """

    evaluated: int
    total: int
    never_evaluated: int
    # Results whose normalized test_id matches no current runnable case: renamed,
    # deleted, or since marked needs_work. Surfaced so "X of Y" is auditable.
    evaluated_unknown: int
    progress_rate: float


class EvalLatestRun(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    source: Optional[str] = None
    total: int
    passed: int
    pass_rate: float


class EvalOverview(BaseModel):
    points: list[EvalBucketPoint]
    # Case-weighted pass rate across the whole window.
    window_pass_rate: Optional[float] = None
    # Pass rate of the most recent run with graded cases. This is the headline number.
    current_pass_rate: Optional[float] = None
    runs: int
    cases: int
    passed: int
    # Runs with total == 0 (aborted, or every case landed in the DLQ). Excluded from the
    # curve because they would otherwise drag a bucket to 0%.
    runs_excluded_no_cases: int
    progress: EvalProgress
    latest_run: Optional[EvalLatestRun] = None


# ---------------------------------------------------------------------------
# KPI tiles
# ---------------------------------------------------------------------------

KpiKey = Literal["feedback_rate", "active_users", "eval_pass_rate", "indexed_sources"]


class OverviewKpi(BaseModel):
    """One headline tile. Values are in native units: rates are 0..1, counts absolute."""

    key: KpiKey
    label: str
    value: Optional[float] = None
    unit: Literal["rate", "count"]
    previous: Optional[float] = None
    change_pct: Optional[float] = None
    # Lets the UI colour the delta without branching per key.
    higher_is_better: bool = True
    sub: Optional[str] = None
    # Per-bucket values for the tile sparkline; aligned with the shared bucket axis.
    series: list[Optional[float]] = []


class OverviewSummaryResponse(BaseModel):
    period: OverviewPeriod
    kpis: list[OverviewKpi]
    feedback: FeedbackOverview
    adoption: AdoptionOverview
    evals: EvalOverview
