"""LLM cost tracking endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section
from app.db import get_db
from app.models.llm_usage import LlmUsageRecord
from app.models.project import Project
from app.schemas.llm_costs import (
    CostDetailItem,
    CostDetailsResponse,
    CostSummaryResponse,
    CostTrendPoint,
    CostTrendResponse,
    ModelCostBreakdown,
    ServiceCostBreakdown,
)

router = APIRouter(prefix="/api/llm-costs", tags=["llm-costs"], dependencies=[require_section("observe")])


def _date_range(
    days: int,
    start_date: datetime | None,
    end_date: datetime | None,
) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if start_date and end_date:
        return start_date, end_date
    if start_date:
        return start_date, now
    return now - timedelta(days=days), now


@router.get("/summary", response_model=CostSummaryResponse)
async def get_cost_summary(
    days: int = Query(30, ge=1, le=365),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    start, end = _date_range(days, start_date, end_date)
    base = [
        LlmUsageRecord.project_id == project.id,
        LlmUsageRecord.created_at >= start,
        LlmUsageRecord.created_at <= end,
    ]

    # Totals
    totals = await db.execute(
        select(
            func.coalesce(func.sum(LlmUsageRecord.cost_usd), 0.0),
            func.coalesce(func.sum(LlmUsageRecord.input_tokens), 0),
            func.coalesce(func.sum(LlmUsageRecord.output_tokens), 0),
            func.count(LlmUsageRecord.id),
        ).where(*base)
    )
    row = totals.one()

    # By service
    svc_q = await db.execute(
        select(
            LlmUsageRecord.service_name,
            func.coalesce(func.sum(LlmUsageRecord.cost_usd), 0.0),
            func.count(LlmUsageRecord.id),
            func.coalesce(func.sum(LlmUsageRecord.input_tokens), 0),
            func.coalesce(func.sum(LlmUsageRecord.output_tokens), 0),
        )
        .where(*base)
        .group_by(LlmUsageRecord.service_name)
        .order_by(func.sum(LlmUsageRecord.cost_usd).desc())
    )
    by_service = [
        ServiceCostBreakdown(
            service_name=r[0], cost_usd=float(r[1]), request_count=r[2],
            input_tokens=r[3], output_tokens=r[4],
        )
        for r in svc_q.all()
    ]

    # By model
    model_q = await db.execute(
        select(
            LlmUsageRecord.model,
            LlmUsageRecord.provider,
            func.coalesce(func.sum(LlmUsageRecord.cost_usd), 0.0),
            func.count(LlmUsageRecord.id),
            func.coalesce(func.sum(LlmUsageRecord.input_tokens), 0),
            func.coalesce(func.sum(LlmUsageRecord.output_tokens), 0),
        )
        .where(*base)
        .group_by(LlmUsageRecord.model, LlmUsageRecord.provider)
        .order_by(func.sum(LlmUsageRecord.cost_usd).desc())
    )
    by_model = [
        ModelCostBreakdown(
            model=r[0], provider=r[1], cost_usd=float(r[2]), request_count=r[3],
            input_tokens=r[4], output_tokens=r[5],
        )
        for r in model_q.all()
    ]

    return CostSummaryResponse(
        total_cost_usd=float(row[0]),
        total_input_tokens=row[1],
        total_output_tokens=row[2],
        total_requests=row[3],
        by_service=by_service,
        by_model=by_model,
    )


@router.get("/trend", response_model=CostTrendResponse)
async def get_cost_trend(
    days: int = Query(30, ge=1, le=365),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    start, end = _date_range(days, start_date, end_date)
    base = [
        LlmUsageRecord.project_id == project.id,
        LlmUsageRecord.created_at >= start,
        LlmUsageRecord.created_at <= end,
    ]

    date_col = cast(LlmUsageRecord.created_at, Date)
    result = await db.execute(
        select(
            date_col.label("date"),
            func.coalesce(func.sum(LlmUsageRecord.cost_usd), 0.0),
            func.count(LlmUsageRecord.id),
            func.coalesce(func.sum(LlmUsageRecord.input_tokens), 0),
            func.coalesce(func.sum(LlmUsageRecord.output_tokens), 0),
        )
        .where(*base)
        .group_by(date_col)
        .order_by(date_col)
    )

    points = [
        CostTrendPoint(
            date=str(r[0]), cost_usd=float(r[1]), request_count=r[2],
            input_tokens=r[3], output_tokens=r[4],
        )
        for r in result.all()
    ]
    return CostTrendResponse(points=points)


@router.get("/details", response_model=CostDetailsResponse)
async def get_cost_details(
    days: int = Query(30, ge=1, le=365),
    service_name: str | None = None,
    model: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    start, end = _date_range(days, start_date, end_date)
    base = [
        LlmUsageRecord.project_id == project.id,
        LlmUsageRecord.created_at >= start,
        LlmUsageRecord.created_at <= end,
    ]
    if service_name:
        base.append(LlmUsageRecord.service_name == service_name)
    if model:
        base.append(LlmUsageRecord.model == model)

    total_q = await db.execute(select(func.count(LlmUsageRecord.id)).where(*base))
    total = total_q.scalar() or 0

    items_q = await db.execute(
        select(LlmUsageRecord)
        .where(*base)
        .order_by(LlmUsageRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [
        CostDetailItem(
            id=r.id,
            service_name=r.service_name,
            function_name=r.function_name,
            provider=r.provider,
            model=r.model,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            total_tokens=r.total_tokens,
            cost_usd=r.cost_usd,
            duration_ms=r.duration_ms,
            created_at=r.created_at,
        )
        for r in items_q.scalars().all()
    ]

    return CostDetailsResponse(items=items, total=total)
