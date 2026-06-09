"""Analytics endpoints — request-type clustering + data-retrieval insights."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section, require_write
from app.db import async_session, get_db
from app.models.models import FeedbackScore, Integration, Span, SpanType, Trace
from app.models.project import Project
from app.models.user import User
from app.routers.dataset_helpers import (
    extract_retrieval_source_urls,
    extract_retrieval_sources,
)
from app.routers.request_clusters_worker import (
    _request_cluster_tasks,
    run_request_cluster_analysis,
)
from app.routers.top_questions import _extract_user_question
from app.schemas.analytics import (
    RequestClusterTheme,
    RequestClustersRequest,
    RequestClustersResponse,
    RequestOutcome,
    RetrievalActivityPoint,
    RetrievalActivityResponse,
    RetrievalSource,
    SpanNameCount,
)
from app.services.observe_filter import get_observe_trace_names
from app.services.retrieval_config import get_retrieval_span_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _trace_base_filter(
    project: Project,
    *,
    environment: str | None,
    include_user_ids: list[str] | None,
    exclude_user_ids: list[str] | None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list:
    """Build the standard Observe trace filter (same shape as the dashboard)."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    filters = [Trace.integration_id.in_(project_integration_ids)]
    if start:
        filters.append(Trace.start_time >= start)
    if end:
        filters.append(Trace.start_time <= end)
    if environment:
        filters.append(Trace.trace_metadata["environment"].astext == environment)
    if include_user_ids:
        filters.append(Trace.user_id.in_(include_user_ids))
    if exclude_user_ids:
        filters.append(~Trace.user_id.in_(exclude_user_ids))
    trace_names = get_observe_trace_names(project)
    if trace_names:
        filters.append(Trace.name.in_(trace_names))
    return filters


def _build_response(analysis) -> RequestClustersResponse:
    themes = []
    for t in analysis.results or []:
        themes.append(RequestClusterTheme(
            rank=t.get("rank", 0),
            theme=t.get("theme", "Unknown"),
            count=t.get("count", 0),
            summary_question=t.get("summary_question", ""),
            trace_ids=t.get("trace_ids", []),
            outcome=RequestOutcome(**(t.get("outcome") or {})),
        ))
    return RequestClustersResponse(
        id=analysis.id,
        status=analysis.status,
        error=analysis.error,
        total_requests=analysis.total_requests,
        processed_requests=analysis.processed_requests,
        themes=themes,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
    )


@router.post(
    "/request-clusters",
    status_code=202,
    dependencies=[require_write("observe", "analytics")],
)
async def analyze_request_clusters(
    body: RequestClustersRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _user: User = Depends(get_current_user),
):
    """Start background clustering of user requests into intent themes."""
    from app.models.analytics import RequestClusterAnalysis
    from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService

    try:
        AnalysisLlmService(user_settings=_user.settings)
    except AnalysisLlmConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))

    base_filter = _trace_base_filter(
        project,
        environment=body.environment,
        include_user_ids=body.include_user_ids,
        exclude_user_ids=body.exclude_user_ids,
        start=body.from_date,
        end=body.to_date,
    )

    rows = (
        await db.execute(
            select(Trace.id, Trace.input, Trace.status)
            .where(*base_filter)
            .order_by(Trace.start_time.desc())
            .limit(body.limit)
        )
    ).all()

    trace_ids = [r[0] for r in rows]
    fb_by_trace: dict[str, float] = {}
    if trace_ids:
        fb_rows = (
            await db.execute(
                select(FeedbackScore.trace_id, FeedbackScore.value).where(
                    FeedbackScore.trace_id.in_(trace_ids),
                    FeedbackScore.score_name == "user-feedback",
                )
            )
        ).all()
        for tid, value in fb_rows:
            fb_by_trace[str(tid)] = value

    requests: list[dict] = []
    for tid, trace_input, status in rows:
        text = _extract_user_question(trace_input)
        if not text:
            continue
        requests.append({
            "request": text[:300],
            "trace_id": str(tid),
            "status": status.value if hasattr(status, "value") else str(status),
            "feedback_value": fb_by_trace.get(str(tid)),
        })

    if len(requests) < 5:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough requests to analyze (found {len(requests)}, minimum 5).",
        )

    analysis = RequestClusterAnalysis(
        project_id=project.id,
        status="pending",
        total_requests=len(requests),
        filter_from_date=body.from_date,
        filter_to_date=body.to_date,
        filter_environment=body.environment,
    )
    db.add(analysis)
    await db.flush()
    await db.refresh(analysis)

    task = asyncio.create_task(
        run_request_cluster_analysis(
            analysis_id=analysis.id,
            requests=requests,
            user_settings=_user.settings,
            db_factory=async_session,
        )
    )
    _request_cluster_tasks[analysis.id] = task

    return {"analysis_id": str(analysis.id), "status": "pending"}


@router.get(
    "/request-clusters/latest",
    response_model=RequestClustersResponse,
    dependencies=[require_section("observe", "analytics")],
)
async def get_latest_request_clusters(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    from app.models.analytics import RequestClusterAnalysis

    result = await db.execute(
        select(RequestClusterAnalysis)
        .where(RequestClusterAnalysis.project_id == project.id)
        .order_by(RequestClusterAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis found")
    return _build_response(analysis)


@router.get(
    "/request-clusters/{analysis_id}",
    response_model=RequestClustersResponse,
    dependencies=[require_section("observe", "analytics")],
)
async def get_request_clusters(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    from app.models.analytics import RequestClusterAnalysis

    analysis = await db.get(RequestClusterAnalysis, analysis_id)
    if not analysis or analysis.project_id != project.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return _build_response(analysis)


@router.post(
    "/request-clusters/{analysis_id}/stop",
    dependencies=[require_write("observe", "analytics")],
)
async def stop_request_clusters(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    from app.models.analytics import RequestClusterAnalysis

    analysis = await db.get(RequestClusterAnalysis, analysis_id)
    if not analysis or analysis.project_id != project.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if analysis.status not in ("pending", "running"):
        return {"message": "Analysis already finished", "status": analysis.status}

    task = _request_cluster_tasks.pop(analysis_id, None)
    if task and not task.done():
        task.cancel()

    analysis.status = "cancelled"
    analysis.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Analysis stopped", "status": "cancelled"}


@router.get(
    "/retrieval/sources",
    response_model=list[RetrievalSource],
    dependencies=[require_section("observe", "analytics")],
)
async def get_retrieval_sources(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    environment: str | None = None,
    include_user_ids: list[str] = Query(None),
    exclude_user_ids: list[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Most frequently retrieved sources, from the project's retrieval-span outputs."""
    base_filter = _trace_base_filter(
        project,
        environment=environment,
        include_user_ids=include_user_ids,
        exclude_user_ids=exclude_user_ids,
        start=from_date,
        end=to_date,
    )
    span_name = get_retrieval_span_name(project)
    rows = (
        await db.execute(
            select(Span.output)
            .join(Trace, Span.trace_id == Trace.id)
            .where(*base_filter, Span.name == span_name)
        )
    ).all()

    counter: Counter[str] = Counter()
    label_by_url: dict[str, str] = {}
    for (output,) in rows:
        for src in extract_retrieval_sources(output):
            url = src["url"]
            counter[url] += 1
            # Keep the first non-trivial label seen for each canonical URL.
            if url not in label_by_url and src["label"] and src["label"] != url:
                label_by_url[url] = src["label"]

    return [
        RetrievalSource(
            url=url,
            domain=urlparse(url).netloc or url,
            label=label_by_url.get(url) or urlparse(url).netloc or url,
            count=count,
        )
        for url, count in counter.most_common(limit)
    ]


@router.get(
    "/retrieval/activity",
    response_model=RetrievalActivityResponse,
    dependencies=[require_section("observe", "analytics")],
)
async def get_retrieval_activity(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    environment: str | None = None,
    include_user_ids: list[str] = Query(None),
    exclude_user_ids: list[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Retrieval coverage (share of requests that retrieved at all), average
    sources pulled per retrieving request, and a daily volume sparkline.

    Date bucketing is done in Python so the same query works on Postgres
    (production) and SQLite (tests) without dialect-specific date casts.
    """
    base_filter = _trace_base_filter(
        project,
        environment=environment,
        include_user_ids=include_user_ids,
        exclude_user_ids=exclude_user_ids,
        start=from_date,
        end=to_date,
    )
    span_name = get_retrieval_span_name(project)

    requests_total = (
        await db.execute(select(func.count()).select_from(Trace).where(*base_filter))
    ).scalar() or 0

    rows = (
        await db.execute(
            select(Span.trace_id, Span.output, Trace.start_time)
            .join(Trace, Span.trace_id == Trace.id)
            # Identify retrieval spans the same way the sources panel does — by the
            # project's configured retrieval span name. The ``retriever`` span type
            # is only set by the LangSmith connector (Langfuse maps its retrieval
            # SPANs to ``chain``), so keep the type check too for LangSmith traces.
            .where(
                *base_filter,
                or_(Span.name == span_name, Span.type == SpanType.retriever),
            )
        )
    ).all()

    daily_counts: dict[str, int] = defaultdict(int)
    sources_by_trace: dict[str, set[str]] = defaultdict(set)
    for trace_id, output, start_time in rows:
        if start_time is not None:
            daily_counts[start_time.date().isoformat()] += 1
        for url in extract_retrieval_source_urls(output):
            sources_by_trace[str(trace_id)].add(url)

    requests_with_retrieval = len({str(r[0]) for r in rows})
    coverage = requests_with_retrieval / requests_total if requests_total else 0.0
    total_sources = sum(len(s) for s in sources_by_trace.values())
    avg_sources = total_sources / requests_with_retrieval if requests_with_retrieval else 0.0

    return RetrievalActivityResponse(
        requests_total=requests_total,
        requests_with_retrieval=requests_with_retrieval,
        coverage=round(coverage, 4),
        avg_sources_per_request=round(avg_sources, 2),
        daily=[
            RetrievalActivityPoint(date=date, count=count)
            for date, count in sorted(daily_counts.items())
        ],
    )


@router.get(
    "/span-names",
    response_model=list[SpanNameCount],
    dependencies=[require_section("observe", "analytics")],
)
async def get_span_names(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Distinct span names in the project with occurrence counts, most frequent
    first — feeds the retrieval span-name picker."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    rows = (
        await db.execute(
            select(Span.name, func.count().label("n"))
            .join(Trace, Span.trace_id == Trace.id)
            .where(
                Trace.integration_id.in_(project_integration_ids),
                Span.name.isnot(None),
                Span.name != "",
            )
            .group_by(Span.name)
            .order_by(func.count().desc())
        )
    ).all()
    return [SpanNameCount(name=name, count=n) for name, n in rows]
