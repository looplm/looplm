"""Combined cost overview — application trace costs + LoopLM platform costs."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section
from app.db import get_db
from app.models.integrations import Integration, Span, SpanType, Trace
from app.models.llm_usage import LlmUsageRecord
from app.models.project import Project
from app.schemas.costs_overview import (
    CostOverviewTrendPoint,
    CostsOverviewResponse,
    ModelCostItem,
    ServiceCostItem,
    ServiceDetailItem,
)
from app.services.llm_pricing import calculate_cost

router = APIRouter(prefix="/api/costs", tags=["costs"], dependencies=[require_section("observe", "costs")])


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


@router.get("/overview", response_model=CostsOverviewResponse)
async def get_costs_overview(
    days: int = Query(30, ge=1, le=365),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    environment: str | None = None,
    include_user_ids: str | None = None,
    exclude_user_ids: str | None = None,
    integration_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    start, end = _date_range(days, start_date, end_date)

    # ── Application costs (from trace spans) ──────────────────────

    project_integrations = select(Integration.id).where(Integration.project_id == project.id)

    span_filters = [
        Trace.integration_id.in_(project_integrations),
        Trace.start_time >= start,
        Trace.start_time <= end,
        Span.type == SpanType.llm,
        Span.tokens_in.isnot(None),
        Span.model.isnot(None),
    ]
    if environment:
        span_filters.append(Trace.trace_metadata["environment"].astext == environment)
    _inc_uids = [v.strip() for v in (include_user_ids or "").split(",") if v.strip()]
    _exc_uids = [v.strip() for v in (exclude_user_ids or "").split(",") if v.strip()]
    if _inc_uids:
        span_filters.append(Trace.user_id.in_(_inc_uids))
    if _exc_uids:
        span_filters.append(~Trace.user_id.in_(_exc_uids))
    if integration_id:
        span_filters.append(Trace.integration_id == integration_id)

    # Group by date + model for trend and breakdown
    app_q = await db.execute(
        select(
            cast(Trace.start_time, Date).label("date"),
            Span.model,
            func.coalesce(func.sum(Span.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(Span.tokens_out), 0).label("tokens_out"),
            func.count(Span.id).label("cnt"),
        )
        .join(Trace, Span.trace_id == Trace.id)
        .where(*span_filters)
        .group_by("date", Span.model)
    )
    app_rows = app_q.all()

    # Calculate costs per row using pricing table
    app_daily: dict[str, dict] = defaultdict(lambda: {"cost": 0.0, "requests": 0})
    app_models: dict[str, dict] = defaultdict(lambda: {"cost": 0.0, "requests": 0, "in": 0, "out": 0})
    total_app_cost = 0.0
    total_app_tokens = 0
    total_app_requests = 0

    for row in app_rows:
        date_str = str(row.date)
        model = row.model or "unknown"
        tokens_in = row.tokens_in
        tokens_out = row.tokens_out
        cnt = row.cnt
        cost = calculate_cost(model, tokens_in, tokens_out) or 0.0

        app_daily[date_str]["cost"] += cost
        app_daily[date_str]["requests"] += cnt

        app_models[model]["cost"] += cost
        app_models[model]["requests"] += cnt
        app_models[model]["in"] += tokens_in
        app_models[model]["out"] += tokens_out

        total_app_cost += cost
        total_app_tokens += tokens_in + tokens_out
        total_app_requests += cnt

    # ── Platform costs (from llm_usage_records) ───────────────────

    platform_base = [
        LlmUsageRecord.project_id == project.id,
        LlmUsageRecord.created_at >= start,
        LlmUsageRecord.created_at <= end,
    ]

    # Fetch raw platform records so we can recalculate NULL costs
    plat_raw_q = await db.execute(
        select(
            cast(LlmUsageRecord.created_at, Date).label("date"),
            LlmUsageRecord.service_name,
            LlmUsageRecord.function_name,
            LlmUsageRecord.model,
            LlmUsageRecord.provider,
            LlmUsageRecord.input_tokens,
            LlmUsageRecord.output_tokens,
            LlmUsageRecord.cost_usd,
        )
        .where(*platform_base)
    )
    plat_rows = plat_raw_q.all()

    plat_daily: dict[str, dict] = defaultdict(lambda: {"cost": 0.0, "requests": 0})
    plat_svc: dict[str, dict] = defaultdict(lambda: {"cost": 0.0, "requests": 0, "in": 0, "out": 0})
    plat_mdl: dict[tuple[str, str], dict] = defaultdict(lambda: {"cost": 0.0, "requests": 0, "in": 0, "out": 0})
    plat_svc_detail: dict[tuple[str, str, str, str], dict] = defaultdict(lambda: {"cost": 0.0, "requests": 0, "in": 0, "out": 0})
    total_platform_cost = 0.0
    total_platform_tokens = 0
    total_platform_requests = 0

    for row in plat_rows:
        cost = row.cost_usd
        if cost is None:
            cost = calculate_cost(row.model, row.input_tokens, row.output_tokens) or 0.0

        date_str = str(row.date)
        plat_daily[date_str]["cost"] += cost
        plat_daily[date_str]["requests"] += 1

        plat_svc[row.service_name]["cost"] += cost
        plat_svc[row.service_name]["requests"] += 1
        plat_svc[row.service_name]["in"] += row.input_tokens
        plat_svc[row.service_name]["out"] += row.output_tokens

        detail_key = (row.service_name, row.function_name, row.model, row.provider)
        plat_svc_detail[detail_key]["cost"] += cost
        plat_svc_detail[detail_key]["requests"] += 1
        plat_svc_detail[detail_key]["in"] += row.input_tokens
        plat_svc_detail[detail_key]["out"] += row.output_tokens

        plat_mdl[(row.model, row.provider)]["cost"] += cost
        plat_mdl[(row.model, row.provider)]["requests"] += 1
        plat_mdl[(row.model, row.provider)]["in"] += row.input_tokens
        plat_mdl[(row.model, row.provider)]["out"] += row.output_tokens

        total_platform_cost += cost
        total_platform_tokens += row.input_tokens + row.output_tokens
        total_platform_requests += 1

    # ── Merge daily trends ────────────────────────────────────────

    all_dates = sorted(set(app_daily.keys()) | set(plat_daily.keys()))
    trend = []
    for d in all_dates:
        ac = app_daily.get(d, {"cost": 0.0, "requests": 0})
        pc = plat_daily.get(d, {"cost": 0.0, "requests": 0})
        trend.append(CostOverviewTrendPoint(
            date=d,
            app_cost_usd=round(ac["cost"], 6),
            platform_cost_usd=round(pc["cost"], 6),
            total_cost_usd=round(ac["cost"] + pc["cost"], 6),
            app_requests=ac["requests"],
            platform_requests=pc["requests"],
        ))

    # ── Build response ────────────────────────────────────────────

    app_by_model = sorted(
        [
            ModelCostItem(
                model=m, provider="app", cost_usd=round(d["cost"], 6),
                request_count=d["requests"], input_tokens=d["in"], output_tokens=d["out"],
            )
            for m, d in app_models.items()
        ],
        key=lambda x: x.cost_usd,
        reverse=True,
    )

    platform_by_service = sorted(
        [
            ServiceCostItem(
                service_name=svc, cost_usd=round(d["cost"], 6),
                request_count=d["requests"], input_tokens=d["in"], output_tokens=d["out"],
                by_detail=sorted(
                    [
                        ServiceDetailItem(
                            function_name=key[1], model=key[2], provider=key[3],
                            cost_usd=round(v["cost"], 6),
                            request_count=v["requests"],
                            input_tokens=v["in"], output_tokens=v["out"],
                        )
                        for key, v in plat_svc_detail.items()
                        if key[0] == svc
                    ],
                    key=lambda x: x.cost_usd,
                    reverse=True,
                ),
            )
            for svc, d in plat_svc.items()
        ],
        key=lambda x: x.cost_usd,
        reverse=True,
    )

    platform_by_model = sorted(
        [
            ModelCostItem(
                model=key[0], provider=key[1], cost_usd=round(d["cost"], 6),
                request_count=d["requests"], input_tokens=d["in"], output_tokens=d["out"],
            )
            for key, d in plat_mdl.items()
        ],
        key=lambda x: x.cost_usd,
        reverse=True,
    )

    return CostsOverviewResponse(
        total_cost_usd=round(total_app_cost + total_platform_cost, 6),
        app_cost_usd=round(total_app_cost, 6),
        platform_cost_usd=round(total_platform_cost, 6),
        total_app_tokens=total_app_tokens,
        total_platform_tokens=total_platform_tokens,
        total_app_requests=total_app_requests,
        total_platform_requests=total_platform_requests,
        trend=trend,
        app_by_model=app_by_model,
        platform_by_service=platform_by_service,
        platform_by_model=platform_by_model,
    )
