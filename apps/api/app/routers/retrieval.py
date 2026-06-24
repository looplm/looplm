"""Retrieval section endpoints — the aggregate retrieval pipeline flow chart.

Phase 1 paints the current retrieval pipeline from traces: a fixed canonical topology
(query → expansion → embeddings → hybrid search → rerank → filter → context → generation
→ judge) annotated with stats rolled up across a window of recent traces. Reconstructed on
read from already-synced span input/output — no re-sync required.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_project, require_section
from app.db import get_db
from app.models.evaluations import EvalResult, EvalRun
from app.models.models import Integration, Trace
from app.models.project import Project
from app.schemas.retrieval import RetrievalPipelineResponse, RetrievalRunMetrics
from app.services.retrieval_config import get_rag_span_names
from app.services.retrieval_metrics_aggregate import aggregate_run_retrieval_metrics
from app.services.retrieval_pipeline_aggregate import build_retrieval_pipeline_aggregate

router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline"],
    dependencies=[require_section("evaluate", "pipeline")],
)

# Cap the window so the per-trace pipeline reconstruction stays bounded. The most recent
# traces are the relevant ones for "what does the pipeline look like now".
_MAX_TRACES = 500


@router.get("/graph", response_model=RetrievalPipelineResponse)
async def get_retrieval_pipeline(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    environment: str | None = None,
    include_user_ids: list[str] = Query(None),
    exclude_user_ids: list[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Aggregate retrieval pipeline flow chart for the project's recent traces."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    filters = [Trace.integration_id.in_(project_integration_ids)]
    if from_date:
        filters.append(Trace.start_time >= from_date)
    if to_date:
        filters.append(Trace.start_time <= to_date)
    if environment:
        filters.append(Trace.trace_metadata["environment"].astext == environment)
    if include_user_ids:
        filters.append(Trace.user_id.in_(include_user_ids))
    if exclude_user_ids:
        filters.append(~Trace.user_id.in_(exclude_user_ids))

    result = await db.execute(
        select(Trace)
        .where(*filters)
        .order_by(Trace.start_time.desc())
        .limit(_MAX_TRACES)
        .options(selectinload(Trace.spans))
    )
    traces = result.scalars().all()

    return build_retrieval_pipeline_aggregate(traces, get_rag_span_names(project))


@router.get("/retrieval-metrics", response_model=RetrievalRunMetrics)
async def get_retrieval_metrics(
    run_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Run-level retrieval-quality metrics (recall@k / precision@k / MRR / nDCG).

    Computed from the ``contains_urls`` evaluator's per-case captures vs each test case's
    ground-truth URLs. Defaults to the project's most recent eval run when ``run_id`` is
    omitted; returns ``available=False`` when the run has no cases with ground-truth URLs.
    """
    run_filter = [EvalRun.project_id == project.id]
    if run_id is not None:
        run_filter.append(EvalRun.id == run_id)

    run = (
        await db.execute(
            select(EvalRun).where(*run_filter).order_by(EvalRun.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Eval run not found"}},
        )

    results = (
        await db.execute(select(EvalResult).where(EvalResult.run_id == run.id))
    ).scalars().all()

    return aggregate_run_retrieval_metrics(run, results)
