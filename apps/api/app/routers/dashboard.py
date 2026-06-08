"""Dashboard endpoints."""

import math
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section
from app.db import get_db
from app.models.models import (
    Analysis,
    FeedbackScore,
    FixStatus,
    FixSuggestion,
    Integration,
    Trace,
    TraceStatus,
)
from app.models.project import Project
from app.services.observe_filter import get_observe_trace_names
from app.schemas.dashboard import (
    DashboardPeriod,
    DashboardStatsResponse,
    DashboardTotals,
    FeedbackSummary,
    FixesStats,
    LatencyPercentiles,
    RegressionFlag,
    ThreadMetrics,
    TopFailure,
    TrendPoint,
)

# A metric must worsen by at least this fraction vs the previous window to flag.
_REGRESSION_MIN_REL = 0.25

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[require_section("observe", "dashboard")])


def _percentile(sorted_vals: list[int], pct: float) -> int | None:
    """Linear-interpolated percentile over a pre-sorted list.

    Computed in Python (not via SQL ``percentile_cont``) so it works
    identically on Postgres and the SQLite test database.
    """
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return int(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return int(sorted_vals[int(k)])
    lower = sorted_vals[f] * (c - k)
    upper = sorted_vals[c] * (k - f)
    return int(round(lower + upper))


def _compute_latency(durations: list[int]) -> LatencyPercentiles:
    """Latency percentiles from raw trace durations (ms)."""
    s = sorted(int(d) for d in durations)
    return LatencyPercentiles(
        count=len(s),
        p50_ms=_percentile(s, 50),
        p95_ms=_percentile(s, 95),
        p99_ms=_percentile(s, 99),
    )


def _regression_flag(
    metric: str, label: str, current: float, previous: float
) -> RegressionFlag:
    """Build a regression flag for a 'higher is worse' metric vs the prior window."""
    if previous > 0:
        change = (current - previous) / previous
    else:
        # No prior baseline: only flag if the current value appeared from nothing.
        change = 1.0 if current > 0 else 0.0
    return RegressionFlag(
        metric=metric,
        label=label,
        current=round(current, 4),
        previous=round(previous, 4),
        change_pct=round(change, 4),
        regressed=previous > 0 and change >= _REGRESSION_MIN_REL,
    )


def _compute_regressions(
    *, cur_failure_rate: float, prev_failure_rate: float, cur_p95: int | None, prev_p95: int | None
) -> list[RegressionFlag]:
    flags = [
        _regression_flag("failure_rate", "Failure rate", cur_failure_rate, prev_failure_rate),
        _regression_flag("latency_p95", "p95 latency", float(cur_p95 or 0), float(prev_p95 or 0)),
    ]
    return [f for f in flags if f.regressed]


def _compute_thread_metrics(rows: list[tuple[int, int]]) -> ThreadMetrics:
    """Conversation metrics from per-thread ``(trace_count, failure_count)`` rows."""
    lengths = sorted(int(c) for c, _ in rows)
    total = len(rows)
    multi = sum(1 for n in lengths if n > 1)
    with_failure = [(c, f) for c, f in rows if f > 0]
    # Of threads that hit a failure, how many continued past it (a retry)?
    retried = sum(1 for c, f in with_failure if c > f)
    return ThreadMetrics(
        total_threads=total,
        multi_turn_threads=multi,
        multi_turn_rate=round(multi / total, 3) if total else 0.0,
        avg_thread_length=round(sum(lengths) / total, 2) if total else 0.0,
        p95_thread_length=_percentile(lengths, 95) or 0,
        retry_rate=round(retried / len(with_failure), 3) if with_failure else 0.0,
    )


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    integration_id: UUID | None = None,
    days: int = Query(7, ge=1, le=90),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    environment: str | None = None,
    include_user_ids: list[str] = Query(None),
    exclude_user_ids: list[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    now = datetime.now(timezone.utc)
    if start_date and end_date:
        start = start_date
        now = end_date
    elif start_date:
        start = start_date
    else:
        start = now - timedelta(days=days)

    # Scope to project's integrations
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    # Project-level trace-name filter (empty/missing = all traces)
    trace_names = get_observe_trace_names(project)

    # Base filter
    base_filter = [Trace.start_time >= start, Trace.start_time <= now, Trace.integration_id.in_(project_integration_ids)]
    if integration_id:
        base_filter.append(Trace.integration_id == integration_id)
    if environment:
        base_filter.append(Trace.trace_metadata["environment"].astext == environment)
    if include_user_ids:
        base_filter.append(Trace.user_id.in_(include_user_ids))
    if exclude_user_ids:
        base_filter.append(~Trace.user_id.in_(exclude_user_ids))
    if trace_names:
        base_filter.append(Trace.name.in_(trace_names))

    # Totals (including unique users/threads)
    totals_q = select(
        func.count(Trace.id).label("total"),
        func.count(Trace.id).filter(Trace.status == TraceStatus.failure).label("failures"),
        func.count(Trace.id).filter(Trace.status == TraceStatus.degraded).label("degraded"),
        func.count(Trace.id).filter(Trace.status == TraceStatus.success).label("success"),
        func.count(func.distinct(Trace.user_id)).label("unique_users"),
        func.count(func.distinct(Trace.thread_id)).label("unique_threads"),
    ).where(*base_filter)
    row = (await db.execute(totals_q)).one()
    total = row.total or 0
    failures = row.failures or 0
    degraded = row.degraded or 0
    success = row.success or 0
    unique_users = row.unique_users or 0
    unique_threads = row.unique_threads or 0
    failure_rate = round(failures / total, 3) if total > 0 else 0.0

    # Top failures from analyses
    top_q = (
        select(
            Analysis.failure_type,
            func.count(Analysis.id).label("cnt"),
            func.min(cast(Analysis.trace_id, String)).label("example_trace_id"),
        )
        .join(Trace, Analysis.trace_id == Trace.id)
        .where(*base_filter, Analysis.failure_type.isnot(None))
        .group_by(Analysis.failure_type)
        .order_by(func.count(Analysis.id).desc())
        .limit(5)
    )
    top_rows = (await db.execute(top_q)).all()
    total_failures_analyzed = sum(r.cnt for r in top_rows) if top_rows else 1
    top_failures = [
        TopFailure(
            failure_type=r.failure_type,
            count=r.cnt,
            percentage=round(r.cnt / total_failures_analyzed, 3),
            example_trace_id=r.example_trace_id,
        )
        for r in top_rows
    ]

    # Daily trends (traces + users + threads)
    trend_q = (
        select(
            cast(Trace.start_time, Date).label("date"),
            func.count(Trace.id).label("total"),
            func.count(Trace.id).filter(Trace.status == TraceStatus.failure).label("failures"),
            func.count(func.distinct(Trace.user_id)).label("unique_users"),
            func.count(func.distinct(Trace.thread_id)).label("unique_threads"),
        )
        .where(*base_filter)
        .group_by(cast(Trace.start_time, Date))
        .order_by(cast(Trace.start_time, Date))
    )
    trend_rows = (await db.execute(trend_q)).all()

    # Daily feedback counts (user-feedback scores joined to traces in period)
    fb_base_filter = [
        FeedbackScore.integration_id.in_(project_integration_ids),
        FeedbackScore.score_name == "user-feedback",
        FeedbackScore.scored_at >= start,
        FeedbackScore.scored_at <= now,
    ]
    if integration_id:
        fb_base_filter.append(FeedbackScore.integration_id == integration_id)

    fb_daily_q = (
        select(
            cast(FeedbackScore.scored_at, Date).label("date"),
            func.sum(case((FeedbackScore.value == 1, 1), else_=0)).label("positive"),
            func.sum(case((FeedbackScore.value == 0, 1), else_=0)).label("negative"),
        )
        .where(*fb_base_filter)
    )
    fb_needs_join = bool(environment or include_user_ids or exclude_user_ids or trace_names)
    if fb_needs_join:
        fb_daily_q = fb_daily_q.join(Trace, FeedbackScore.trace_id == Trace.id)
        if environment:
            fb_daily_q = fb_daily_q.where(Trace.trace_metadata["environment"].astext == environment)
        if include_user_ids:
            fb_daily_q = fb_daily_q.where(Trace.user_id.in_(include_user_ids))
        if exclude_user_ids:
            fb_daily_q = fb_daily_q.where(~Trace.user_id.in_(exclude_user_ids))
        if trace_names:
            fb_daily_q = fb_daily_q.where(Trace.name.in_(trace_names))
    fb_daily_q = fb_daily_q.group_by(cast(FeedbackScore.scored_at, Date))
    fb_daily_rows = (await db.execute(fb_daily_q)).all()
    fb_by_date = {str(r.date): (int(r.positive or 0), int(r.negative or 0)) for r in fb_daily_rows}

    # Daily count of distinct traces that received at least one feedback
    fb_traces_q = (
        select(
            cast(FeedbackScore.scored_at, Date).label("date"),
            func.count(func.distinct(FeedbackScore.trace_id)).label("traces_with_fb"),
        )
        .where(*fb_base_filter, FeedbackScore.trace_id.isnot(None))
    )
    if fb_needs_join:
        fb_traces_q = fb_traces_q.join(Trace, FeedbackScore.trace_id == Trace.id)
        if environment:
            fb_traces_q = fb_traces_q.where(Trace.trace_metadata["environment"].astext == environment)
        if include_user_ids:
            fb_traces_q = fb_traces_q.where(Trace.user_id.in_(include_user_ids))
        if exclude_user_ids:
            fb_traces_q = fb_traces_q.where(~Trace.user_id.in_(exclude_user_ids))
        if trace_names:
            fb_traces_q = fb_traces_q.where(Trace.name.in_(trace_names))
    fb_traces_q = fb_traces_q.group_by(cast(FeedbackScore.scored_at, Date))
    fb_traces_rows = (await db.execute(fb_traces_q)).all()
    fb_traces_by_date = {str(r.date): int(r.traces_with_fb or 0) for r in fb_traces_rows}

    trends = [
        TrendPoint(
            date=str(r.date),
            total=r.total,
            failures=r.failures,
            failure_rate=round(r.failures / r.total, 3) if r.total > 0 else 0.0,
            unique_users=r.unique_users or 0,
            unique_threads=r.unique_threads or 0,
            feedback_positive=fb_by_date.get(str(r.date), (0, 0))[0],
            feedback_negative=fb_by_date.get(str(r.date), (0, 0))[1],
            traces_with_feedback=fb_traces_by_date.get(str(r.date), 0),
        )
        for r in trend_rows
    ]

    # Feedback summary — reuse the same date/environment/user filters as trends
    fb_summary_filter = list(fb_base_filter)
    fb_summary_total_q = select(func.count(FeedbackScore.id)).where(*fb_summary_filter)
    fb_summary_pos_q = select(func.count(FeedbackScore.id)).where(*fb_summary_filter, FeedbackScore.value == 1)
    fb_summary_traces_q = select(func.count(func.distinct(FeedbackScore.trace_id))).where(
        *fb_summary_filter, FeedbackScore.trace_id.isnot(None)
    )
    if fb_needs_join:
        fb_summary_total_q = fb_summary_total_q.join(Trace, FeedbackScore.trace_id == Trace.id)
        fb_summary_pos_q = fb_summary_pos_q.join(Trace, FeedbackScore.trace_id == Trace.id)
        fb_summary_traces_q = fb_summary_traces_q.join(Trace, FeedbackScore.trace_id == Trace.id)
        if environment:
            fb_summary_total_q = fb_summary_total_q.where(Trace.trace_metadata["environment"].astext == environment)
            fb_summary_pos_q = fb_summary_pos_q.where(Trace.trace_metadata["environment"].astext == environment)
            fb_summary_traces_q = fb_summary_traces_q.where(Trace.trace_metadata["environment"].astext == environment)
        if include_user_ids:
            fb_summary_total_q = fb_summary_total_q.where(Trace.user_id.in_(include_user_ids))
            fb_summary_pos_q = fb_summary_pos_q.where(Trace.user_id.in_(include_user_ids))
            fb_summary_traces_q = fb_summary_traces_q.where(Trace.user_id.in_(include_user_ids))
        if exclude_user_ids:
            fb_summary_total_q = fb_summary_total_q.where(~Trace.user_id.in_(exclude_user_ids))
            fb_summary_pos_q = fb_summary_pos_q.where(~Trace.user_id.in_(exclude_user_ids))
            fb_summary_traces_q = fb_summary_traces_q.where(~Trace.user_id.in_(exclude_user_ids))
        if trace_names:
            fb_summary_total_q = fb_summary_total_q.where(Trace.name.in_(trace_names))
            fb_summary_pos_q = fb_summary_pos_q.where(Trace.name.in_(trace_names))
            fb_summary_traces_q = fb_summary_traces_q.where(Trace.name.in_(trace_names))

    total_fb = (await db.execute(fb_summary_total_q)).scalar() or 0
    positive_fb = (await db.execute(fb_summary_pos_q)).scalar() or 0
    negative_fb = total_fb - positive_fb

    traces_with_fb = (await db.execute(fb_summary_traces_q)).scalar() or 0
    no_feedback_traces = total - traces_with_fb

    positive_rate = round(positive_fb / total_fb, 3) if total_fb > 0 else 0.0

    # Fix stats — scoped to project's data
    project_trace_ids = select(Trace.id).where(Trace.integration_id.in_(project_integration_ids))
    user_analysis_ids = select(Analysis.id).where(Analysis.trace_id.in_(project_trace_ids))
    fix_q = select(
        func.count(FixSuggestion.id).label("suggested"),
        func.count(FixSuggestion.id).filter(FixSuggestion.status == FixStatus.applied).label("applied"),
        func.count(FixSuggestion.id).filter(FixSuggestion.status == FixStatus.dismissed).label("dismissed"),
        func.count(FixSuggestion.id).filter(FixSuggestion.status == FixStatus.pending).label("pending"),
    ).where(FixSuggestion.analysis_id.in_(user_analysis_ids))
    fix_row = (await db.execute(fix_q)).one()

    # Latency percentiles — tails reveal problems that the average hides.
    dur_vals = (
        await db.execute(
            select(Trace.duration_ms).where(*base_filter, Trace.duration_ms.isnot(None))
        )
    ).scalars().all()
    latency = _compute_latency(list(dur_vals))

    # Thread (conversation) metrics — group the windowed traces by thread_id.
    thread_q = (
        select(
            func.count(Trace.id).label("cnt"),
            func.count(Trace.id).filter(Trace.status == TraceStatus.failure).label("failures"),
        )
        .where(*base_filter, Trace.thread_id.isnot(None))
        .group_by(Trace.thread_id)
    )
    thread_rows = (await db.execute(thread_q)).all()
    threads = _compute_thread_metrics([(int(r.cnt), int(r.failures or 0)) for r in thread_rows])

    # Regression check vs the immediately-preceding window of equal length.
    window = now - start
    prev_start = start - window
    # base_filter[0:2] are the current-window time bounds; reuse the rest verbatim.
    prev_filter = [Trace.start_time >= prev_start, Trace.start_time < start, *base_filter[2:]]
    prev_totals = (
        await db.execute(
            select(
                func.count(Trace.id).label("total"),
                func.count(Trace.id).filter(Trace.status == TraceStatus.failure).label("failures"),
            ).where(*prev_filter)
        )
    ).one()
    prev_total = prev_totals.total or 0
    prev_failure_rate = round((prev_totals.failures or 0) / prev_total, 3) if prev_total else 0.0
    prev_dur_vals = (
        await db.execute(
            select(Trace.duration_ms).where(*prev_filter, Trace.duration_ms.isnot(None))
        )
    ).scalars().all()
    prev_p95 = _percentile(sorted(int(d) for d in prev_dur_vals), 95)
    regressions = _compute_regressions(
        cur_failure_rate=failure_rate,
        prev_failure_rate=prev_failure_rate,
        cur_p95=latency.p95_ms,
        prev_p95=prev_p95,
    )

    return DashboardStatsResponse(
        period=DashboardPeriod(start=start, end=now),
        totals=DashboardTotals(
            traces=total,
            failures=failures,
            degraded=degraded,
            success=success,
            failure_rate=failure_rate,
            unique_users=unique_users,
            unique_threads=unique_threads,
        ),
        top_failures=top_failures,
        trends=trends,
        fixes=FixesStats(
            suggested=fix_row.suggested,
            applied=fix_row.applied,
            dismissed=fix_row.dismissed,
            pending=fix_row.pending,
        ),
        feedback=FeedbackSummary(
            total=total_fb,
            positive=positive_fb,
            negative=negative_fb,
            positive_rate=positive_rate,
            no_feedback_traces=no_feedback_traces,
        ),
        latency=latency,
        threads=threads,
        regressions=regressions,
    )
