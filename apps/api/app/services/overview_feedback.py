"""Positive/negative end-user feedback, bucketed over time.

Deliberately separate from ``services/feedback_stats_service.py``, which powers the
Feedback page: that one buckets on ``FeedbackScore.scored_at``, is hard-coded to daily,
and also computes grader trends and verdict filters the Overview does not want. Calling
it would mean fetching four unused result sets and, worse, drawing a feedback chart on a
different time axis from the volume chart right next to it.

``feedback_trend_series`` is parameterized by date column and bucket so the two can
converge later without changing the Feedback page's semantics in the same commit.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import FeedbackScore, Trace
from app.models.project import Project
from app.schemas.overview_summary import (
    FeedbackBucketPoint,
    FeedbackOverview,
    FeedbackTotals,
)
from app.services.time_buckets import Bucket, date_bucket, safe_rate
from app.services.trace_scope import trace_scope_filters

# The score_name end users' thumbs arrive under. Anything else is a grader or an
# online-eval score and must not count as user sentiment.
USER_FEEDBACK_SCORE_NAME = "user-feedback"


async def feedback_trend_series(
    db: AsyncSession,
    *,
    scope: list,
    bucket: Bucket,
    date_column=Trace.start_time,
) -> dict[str, tuple[int, int, int, int]]:
    """Bucketed (total, positive, negative, traces_with_feedback) keyed by bucket label.

    ``scope`` is the trace filter list from ``trace_scope_filters``. The inner join to
    ``Trace`` is what applies it, and it also drops scores with a null ``trace_id``.
    """
    label = date_bucket(date_column, bucket).label("bucket")
    query = (
        select(
            label,
            func.count(FeedbackScore.id).label("total"),
            # sum(case(...)) rather than count().filter(...): aggregate FILTER needs
            # SQLite >= 3.30 and these queries actually run on SQLite in the test suite.
            func.sum(case((FeedbackScore.value == 1, 1), else_=0)).label("positive"),
            func.sum(case((FeedbackScore.value == 0, 1), else_=0)).label("negative"),
            func.count(func.distinct(FeedbackScore.trace_id)).label("traces_with_fb"),
        )
        .join(Trace, FeedbackScore.trace_id == Trace.id)
        .where(FeedbackScore.score_name == USER_FEEDBACK_SCORE_NAME, *scope)
        .group_by(label)
        .order_by(label)
    )
    rows = (await db.execute(query)).all()
    return {
        str(r.bucket): (
            int(r.total or 0),
            int(r.positive or 0),
            int(r.negative or 0),
            int(r.traces_with_fb or 0),
        )
        for r in rows
    }


async def _positive_rate_for_window(
    db: AsyncSession,
    project: Project,
    *,
    start: datetime,
    end: datetime,
    filters: dict,
) -> tuple[float, int]:
    """(positive_rate, total) for a window, used for the previous-period comparison."""
    scope = trace_scope_filters(project, start=start, end=end, **filters)
    query = (
        select(
            func.count(FeedbackScore.id).label("total"),
            func.sum(case((FeedbackScore.value == 1, 1), else_=0)).label("positive"),
        )
        .join(Trace, FeedbackScore.trace_id == Trace.id)
        .where(FeedbackScore.score_name == USER_FEEDBACK_SCORE_NAME, *scope)
    )
    row = (await db.execute(query)).one()
    total = int(row.total or 0)
    positive = int(row.positive or 0)
    return safe_rate(positive, total), total


async def compute_feedback_overview(
    db: AsyncSession,
    project: Project,
    *,
    start: datetime,
    end: datetime,
    bucket: Bucket,
    axis: list[str],
    filters: dict,
) -> FeedbackOverview:
    """Build the feedback section for the selected window."""
    scope = trace_scope_filters(project, start=start, end=end, **filters)
    by_bucket = await feedback_trend_series(db, scope=scope, bucket=bucket)

    points: list[FeedbackBucketPoint] = []
    total = positive = negative = traces_with_feedback = 0
    for label in axis:
        b_total, b_pos, b_neg, b_traces = by_bucket.get(label, (0, 0, 0, 0))
        total += b_total
        positive += b_pos
        negative += b_neg
        traces_with_feedback += b_traces
        points.append(
            FeedbackBucketPoint(
                bucket=label,
                total=b_total,
                positive=b_pos,
                negative=b_neg,
                traces_with_feedback=b_traces,
                positive_rate=safe_rate(b_pos, b_total),
            )
        )

    return FeedbackOverview(
        points=points,
        totals=FeedbackTotals(
            total=total,
            positive=positive,
            negative=negative,
            positive_rate=safe_rate(positive, total),
            traces_with_feedback=traces_with_feedback,
        ),
    )


async def previous_feedback_rate(
    db: AsyncSession,
    project: Project,
    *,
    start: datetime,
    end: datetime,
    filters: dict,
) -> tuple[float, int]:
    """Positive rate and submission count for the preceding equal-length window."""
    return await _positive_rate_for_window(
        db, project, start=start, end=end, filters=filters
    )
