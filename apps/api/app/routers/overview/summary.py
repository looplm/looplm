"""GET /api/overview/summary — feedback, adoption and evals on one shared bucket axis."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project
from app.db import get_db
from app.models.project import Project
from app.schemas.overview_common import OverviewPeriod
from app.schemas.overview_summary import OverviewKpi, OverviewSummaryResponse
from app.services.overview_adoption import compute_adoption_overview
from app.services.overview_evals import compute_eval_overview, window_pass_rate
from app.services.overview_feedback import compute_feedback_overview, previous_feedback_rate
from app.services.overview_sources import count_indexed_sources
from app.services.time_buckets import (
    MAX_BUCKETS,
    Bucket,
    bucket_axis,
    normalize_range,
    pct_change,
    previous_window,
)

router = APIRouter()


def _build_kpis(
    *,
    feedback,
    adoption,
    evals,
    previous_positive_rate: float | None,
    previous_pass_rate: float | None,
    source_count: int,
    provider_count: int,
) -> list[OverviewKpi]:
    """The four headline tiles, in native units.

    Deltas live here rather than in the sections so the UI has one place to read them.
    """
    fb_rate = feedback.totals.positive_rate if feedback.totals.total else None
    return [
        OverviewKpi(
            key="feedback_rate",
            label="Positive feedback",
            value=fb_rate,
            unit="rate",
            previous=previous_positive_rate,
            change_pct=pct_change(fb_rate, previous_positive_rate),
            higher_is_better=True,
            sub=(
                f"{feedback.totals.positive} positive, {feedback.totals.negative} negative"
                if feedback.totals.total
                else "No feedback in this period"
            ),
            series=[p.positive_rate if p.total else None for p in feedback.points],
        ),
        OverviewKpi(
            key="active_users",
            label="Active users",
            value=float(adoption.totals.active_users),
            unit="count",
            previous=adoption.growth.active_users.previous,
            change_pct=adoption.growth.active_users.change_pct,
            higher_is_better=True,
            sub=(
                f"{adoption.totals.new_users} new, "
                f"{adoption.totals.returning_users} returning"
            ),
            series=[float(p.active_users) for p in adoption.points],
        ),
        OverviewKpi(
            key="eval_pass_rate",
            label="Eval pass rate",
            value=evals.current_pass_rate,
            unit="rate",
            previous=previous_pass_rate,
            change_pct=pct_change(evals.current_pass_rate, previous_pass_rate),
            higher_is_better=True,
            sub=(
                f"{evals.progress.evaluated} of {evals.progress.total} cases evaluated"
                if evals.progress.total
                else "No test cases yet"
            ),
            series=[p.pass_rate for p in evals.points],
        ),
        OverviewKpi(
            key="indexed_sources",
            label="Indexed sources",
            # None, not 0, when nothing is connected: zero would claim an empty index,
            # while null lets the UI say "not configured".
            value=float(source_count) if provider_count else None,
            unit="count",
            # Index state is a level with no history, so there is nothing to compare to.
            previous=None,
            change_pct=None,
            higher_is_better=True,
            sub=(
                f"{provider_count} provider{'s' if provider_count != 1 else ''}"
                if provider_count
                else "No index provider connected"
            ),
            series=[],
        ),
    ]


@router.get("/summary", response_model=OverviewSummaryResponse)
async def overview_summary(
    bucket: Bucket = "day",
    days: int = Query(30, ge=1, le=730),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    environment: Optional[str] = None,
    integration_id: Optional[UUID] = None,
    include_user_ids: Annotated[Optional[list[str]], Query()] = None,
    exclude_user_ids: Annotated[Optional[list[str]], Query()] = None,
    include_reruns: bool = True,
    sources: Optional[str] = None,
    dataset_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Feedback sentiment, user adoption and eval pass rate for one window.

    All three series share the bucket axis built here, so column *i* of every chart and
    every KPI sparkline refers to the same period.
    """
    start, end = normalize_range(days, start_date, end_date)
    axis = bucket_axis(start, end, bucket)
    if len(axis) > MAX_BUCKETS:
        # Refused rather than silently coarsened: a chart that quietly changed its own
        # granularity would misreport what the user asked for.
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "RANGE_TOO_LARGE",
                    "message": (
                        f"{len(axis)} {bucket} buckets exceeds the {MAX_BUCKETS} limit. "
                        "Narrow the range or use a larger bucket."
                    ),
                }
            },
        )

    prev_start, prev_end = previous_window(start, end)
    filters = {
        "environment": environment,
        "include_user_ids": include_user_ids,
        "exclude_user_ids": exclude_user_ids,
        "integration_id": integration_id,
    }

    feedback = await compute_feedback_overview(
        db, project, start=start, end=end, bucket=bucket, axis=axis, filters=filters
    )
    prev_positive_rate, prev_feedback_total = await previous_feedback_rate(
        db, project, start=prev_start, end=prev_end, filters=filters
    )
    adoption = await compute_adoption_overview(
        db,
        project,
        start=start,
        end=end,
        bucket=bucket,
        axis=axis,
        previous=(prev_start, prev_end),
        filters=filters,
    )
    evals = await compute_eval_overview(
        db,
        project,
        start=start,
        end=end,
        bucket=bucket,
        axis=axis,
        include_reruns=include_reruns,
        sources=sources,
        dataset_id=str(dataset_id) if dataset_id else None,
    )
    prev_pass_rate = await window_pass_rate(
        db,
        project,
        start=prev_start,
        end=prev_end,
        include_reruns=include_reruns,
        sources=sources,
    )
    source_count, provider_count = await count_indexed_sources(db, project)

    return OverviewSummaryResponse(
        period=OverviewPeriod(
            start=start,
            end=end,
            bucket=bucket,
            buckets=len(axis),
            previous_start=prev_start,
            previous_end=prev_end,
        ),
        kpis=_build_kpis(
            feedback=feedback,
            adoption=adoption,
            evals=evals,
            # None when the previous window had no feedback at all, so the delta is
            # omitted instead of comparing against a fabricated zero rate.
            previous_positive_rate=prev_positive_rate if prev_feedback_total else None,
            previous_pass_rate=prev_pass_rate,
            source_count=source_count,
            provider_count=provider_count,
        ),
        feedback=feedback,
        adoption=adoption,
        evals=evals,
    )
