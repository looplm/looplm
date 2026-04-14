"""Dashboard endpoints."""

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
from app.schemas.dashboard import (
    DashboardPeriod,
    DashboardStatsResponse,
    DashboardTotals,
    FeedbackSummary,
    FixesStats,
    TopFailure,
    TrendPoint,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[require_section("observe")])


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
    fb_needs_join = bool(environment or include_user_ids or exclude_user_ids)
    if fb_needs_join:
        fb_daily_q = fb_daily_q.join(Trace, FeedbackScore.trace_id == Trace.id)
        if environment:
            fb_daily_q = fb_daily_q.where(Trace.trace_metadata["environment"].astext == environment)
        if include_user_ids:
            fb_daily_q = fb_daily_q.where(Trace.user_id.in_(include_user_ids))
        if exclude_user_ids:
            fb_daily_q = fb_daily_q.where(~Trace.user_id.in_(exclude_user_ids))
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
    )
