"""Query + trend logic for the feedback /stats endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as tz
from uuid import UUID

from sqlalchemy import case, cast, Date, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import FeedbackScore, Integration, Trace
from app.models.project import Project
from app.schemas.feedback import (
    FeedbackStatsResponse,
    FeedbackTrend,
    GraderStats,
    GraderTrend,
)
from app.services.observe_filter import get_observe_trace_names


async def compute_feedback_stats(
    db: AsyncSession,
    project: Project,
    *,
    days: int = 30,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    environment: str | None = None,
    include_user_ids: str | None = None,
    exclude_user_ids: str | None = None,
    integration_id: UUID | None = None,
) -> FeedbackStatsResponse:
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    base_filter = [FeedbackScore.integration_id.in_(project_integration_ids)]
    if integration_id:
        base_filter.append(FeedbackScore.integration_id == integration_id)

    # Compute date range cutoffs
    if start_date:
        cutoff = start_date
    else:
        cutoff = datetime.now(tz.utc) - timedelta(days=days)
    cutoff_end = end_date or datetime.now(tz.utc)

    # Feedback counts (user-feedback only, filtered by date range + environment)
    fb_filter = [*base_filter, FeedbackScore.score_name == "user-feedback",
                 FeedbackScore.scored_at >= cutoff, FeedbackScore.scored_at <= cutoff_end]

    _inc_uids = [v.strip() for v in (include_user_ids or "").split(",") if v.strip()]
    _exc_uids = [v.strip() for v in (exclude_user_ids or "").split(",") if v.strip()]
    observe_names = get_observe_trace_names(project)
    _needs_trace_join = bool(environment or _inc_uids or _exc_uids or observe_names)
    fb_count_query = select(func.count(FeedbackScore.id)).where(*fb_filter)
    fb_positive_query = select(func.count(FeedbackScore.id)).where(*fb_filter, FeedbackScore.value == 1)
    if _needs_trace_join:
        fb_count_query = fb_count_query.join(Trace, FeedbackScore.trace_id == Trace.id)
        fb_positive_query = fb_positive_query.join(Trace, FeedbackScore.trace_id == Trace.id)
        if environment:
            fb_count_query = fb_count_query.where(Trace.trace_metadata["environment"].astext == environment)
            fb_positive_query = fb_positive_query.where(Trace.trace_metadata["environment"].astext == environment)
        if _inc_uids:
            fb_count_query = fb_count_query.where(Trace.user_id.in_(_inc_uids))
            fb_positive_query = fb_positive_query.where(Trace.user_id.in_(_inc_uids))
        if _exc_uids:
            fb_count_query = fb_count_query.where(~Trace.user_id.in_(_exc_uids))
            fb_positive_query = fb_positive_query.where(~Trace.user_id.in_(_exc_uids))
        if observe_names:
            fb_count_query = fb_count_query.where(Trace.name.in_(observe_names))
            fb_positive_query = fb_positive_query.where(Trace.name.in_(observe_names))

    total_fb = (await db.execute(fb_count_query)).scalar() or 0
    positive = (await db.execute(fb_positive_query)).scalar() or 0
    negative = total_fb - positive

    # Count traces with no feedback (filtered by date range + environment)
    trace_filter = [Trace.integration_id.in_(project_integration_ids),
                    Trace.start_time >= cutoff, Trace.start_time <= cutoff_end]
    if integration_id:
        trace_filter.append(Trace.integration_id == integration_id)
    if environment:
        trace_filter.append(Trace.trace_metadata["environment"].astext == environment)
    if _inc_uids:
        trace_filter.append(Trace.user_id.in_(_inc_uids))
    if _exc_uids:
        trace_filter.append(~Trace.user_id.in_(_exc_uids))
    if observe_names:
        trace_filter.append(Trace.name.in_(observe_names))

    total_traces = (await db.execute(select(func.count(Trace.id)).where(*trace_filter))).scalar() or 0

    fb_with_trace_filter = [*base_filter, FeedbackScore.score_name == "user-feedback",
                            FeedbackScore.scored_at >= cutoff, FeedbackScore.scored_at <= cutoff_end,
                            FeedbackScore.trace_id.isnot(None)]
    fb_with_trace_query = select(func.count(func.distinct(FeedbackScore.trace_id))).where(*fb_with_trace_filter)
    if _needs_trace_join:
        fb_with_trace_query = fb_with_trace_query.join(Trace, FeedbackScore.trace_id == Trace.id)
        if environment:
            fb_with_trace_query = fb_with_trace_query.where(Trace.trace_metadata["environment"].astext == environment)
        if _inc_uids:
            fb_with_trace_query = fb_with_trace_query.where(Trace.user_id.in_(_inc_uids))
        if _exc_uids:
            fb_with_trace_query = fb_with_trace_query.where(~Trace.user_id.in_(_exc_uids))
        if observe_names:
            fb_with_trace_query = fb_with_trace_query.where(Trace.name.in_(observe_names))
    traces_with_fb = (await db.execute(fb_with_trace_query)).scalar() or 0
    no_feedback = total_traces - traces_with_fb

    trend_query = (
        select(
            cast(FeedbackScore.scored_at, Date).label("date"),
            func.count(FeedbackScore.id).label("total"),
            func.sum(case((FeedbackScore.value == 1, 1), else_=0)).label("positive"),
            func.sum(case((FeedbackScore.value == 0, 1), else_=0)).label("negative"),
        )
        .where(*fb_filter)
    )
    if _needs_trace_join:
        trend_query = trend_query.join(Trace, FeedbackScore.trace_id == Trace.id)
        if environment:
            trend_query = trend_query.where(Trace.trace_metadata["environment"].astext == environment)
        if _inc_uids:
            trend_query = trend_query.where(Trace.user_id.in_(_inc_uids))
        if _exc_uids:
            trend_query = trend_query.where(~Trace.user_id.in_(_exc_uids))
        if observe_names:
            trend_query = trend_query.where(Trace.name.in_(observe_names))
    trend_query = trend_query.group_by(cast(FeedbackScore.scored_at, Date)).order_by(cast(FeedbackScore.scored_at, Date))
    trend_result = await db.execute(trend_query)
    trends = [
        FeedbackTrend(
            date=str(row.date),
            positive=int(row.positive or 0),
            negative=int(row.negative or 0),
            total=int(row.total or 0),
        )
        for row in trend_result.all()
    ]

    # Grader stats (all non-user-feedback scores, filtered by date range + environment)
    grader_query = (
        select(
            FeedbackScore.score_name,
            func.count(FeedbackScore.id).label("total"),
            func.sum(case((FeedbackScore.value == 1, 1), else_=0)).label("passed"),
            func.sum(case((FeedbackScore.value == 0, 1), else_=0)).label("failed"),
        )
        .where(*base_filter, FeedbackScore.score_name != "user-feedback",
               FeedbackScore.scored_at >= cutoff, FeedbackScore.scored_at <= cutoff_end)
        .group_by(FeedbackScore.score_name)
        .order_by(FeedbackScore.score_name)
    )
    if _needs_trace_join:
        grader_query = grader_query.join(Trace, FeedbackScore.trace_id == Trace.id)
        if environment:
            grader_query = grader_query.where(Trace.trace_metadata["environment"].astext == environment)
        if _inc_uids:
            grader_query = grader_query.where(Trace.user_id.in_(_inc_uids))
        if _exc_uids:
            grader_query = grader_query.where(~Trace.user_id.in_(_exc_uids))
        if observe_names:
            grader_query = grader_query.where(Trace.name.in_(observe_names))
    grader_result = await db.execute(grader_query)
    grader_stats = [
        GraderStats(
            name=row.score_name,
            total=int(row.total or 0),
            passed=int(row.passed or 0),
            failed=int(row.failed or 0),
            pass_rate=float(row.passed or 0) / float(row.total) if row.total else 0.0,
        )
        for row in grader_result.all()
    ]

    # Daily trends for graders (non-user-feedback)
    grader_trend_query = (
        select(
            FeedbackScore.score_name,
            cast(FeedbackScore.scored_at, Date).label("date"),
            func.count(FeedbackScore.id).label("total"),
            func.sum(case((FeedbackScore.value == 1, 1), else_=0)).label("passed"),
            func.sum(case((FeedbackScore.value == 0, 1), else_=0)).label("failed"),
        )
        .where(*base_filter, FeedbackScore.score_name != "user-feedback", FeedbackScore.scored_at >= cutoff)
    )
    if _needs_trace_join:
        grader_trend_query = grader_trend_query.join(Trace, FeedbackScore.trace_id == Trace.id)
        if environment:
            grader_trend_query = grader_trend_query.where(Trace.trace_metadata["environment"].astext == environment)
        if _inc_uids:
            grader_trend_query = grader_trend_query.where(Trace.user_id.in_(_inc_uids))
        if _exc_uids:
            grader_trend_query = grader_trend_query.where(~Trace.user_id.in_(_exc_uids))
        if observe_names:
            grader_trend_query = grader_trend_query.where(Trace.name.in_(observe_names))
    grader_trend_query = grader_trend_query.group_by(
        FeedbackScore.score_name, cast(FeedbackScore.scored_at, Date)
    ).order_by(FeedbackScore.score_name, cast(FeedbackScore.scored_at, Date))
    grader_trend_result = await db.execute(grader_trend_query)
    grader_trends: dict[str, list[GraderTrend]] = {}
    for row in grader_trend_result.all():
        grader_trends.setdefault(row.score_name, []).append(
            GraderTrend(
                date=str(row.date),
                passed=int(row.passed or 0),
                failed=int(row.failed or 0),
                total=int(row.total or 0),
            )
        )

    return FeedbackStatsResponse(
        total_feedback=total_fb,
        positive=positive,
        negative=negative,
        no_feedback_traces=no_feedback,
        positive_rate=positive / total_fb if total_fb > 0 else 0.0,
        trends=trends,
        grader_stats=grader_stats,
        grader_trends=grader_trends,
    )
