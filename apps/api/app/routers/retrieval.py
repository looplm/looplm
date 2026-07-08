"""Retrieval section endpoints — the aggregate retrieval pipeline flow chart.

Phase 1 paints the current retrieval pipeline from traces: a fixed canonical topology
(query → expansion → embeddings → hybrid search → rerank → filter → context → generation
→ judge) annotated with stats rolled up across a window of recent traces. Reconstructed on
read from already-synced span input/output — no re-sync required.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_project, get_current_user, require_section, require_write
from app.db import get_db
from app.models.evaluations import EvalResult, EvalRun
from app.models.models import Integration, Trace
from app.models.project import Project
from app.models.retrieval_metrics_jobs import RetrievalMetricsJob
from app.models.user import User
from app.schemas.retrieval import (
    ByStageMetricsResponse,
    RetrievalComputeJob,
    RetrievalComputeStart,
    RetrievalPipelineResponse,
    RetrievalRunMetrics,
    RetrievalTargets,
)
from app.services.retrieval_config import get_rag_span_names
from app.services.retrieval_labels_metrics import (
    compute_by_stage_metrics,
    compute_overall_labels_metrics,
    resolve_datasets,
    resolve_slices,
)
from app.services.retrieval_metrics_aggregate import (
    aggregate_run_retrieval_metrics,
    negative_test_ids,
)
from app.services.retrieval_metrics_job import run_metrics_job
from app.services.retrieval_pipeline_aggregate import build_retrieval_pipeline_aggregate
from app.services.retrieval_targets import (
    SETTINGS_KEY as TARGETS_SETTINGS_KEY,
    get_retrieval_targets,
    sanitize_targets,
)

router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline"],
    dependencies=[require_section("evaluate", "pipeline")],
)

# Cap the window so the per-trace pipeline reconstruction stays bounded. The most recent
# traces are the relevant ones for "what does the pipeline look like now".
_MAX_TRACES = 500

# In-process handles to running compute tasks (mirrors eval_jobs._eval_tasks). Best-effort: a
# restart drops them and the lifespan reconcile marks orphaned rows failed.
_metrics_jobs: dict[UUID, asyncio.Task] = {}


def _job_view(job: RetrievalMetricsJob) -> RetrievalComputeJob:
    return RetrievalComputeJob(
        id=str(job.id),
        status=job.status,
        view=job.view,
        gold_source=job.gold_source,
        min_grade=job.min_grade or 1,
        dataset_ids=list(job.dataset_ids or []),
        progress_current=job.progress_current,
        progress_total=job.progress_total,
        error=job.error,
        trace=job.trace,
    )


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
    dataset_id: UUID | None = None,
    dataset_ids: list[UUID] | None = Query(None),
    source: str = "urls",
    refresh: bool = False,
    gold_source: str = "human",
    min_grade: int = Query(1, ge=1, le=3),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Retrieval-quality metrics (recall@k / precision@k / MRR / nDCG).

    ``source=labels`` measures pooled chunk labels against a *live retrieval probe* of the
    connected index, over one or more datasets' test cases (``dataset_ids``; ``dataset_id`` is the
    single-dataset alias; default most-recent). This is the data-labeling lens and needs no eval
    run. ``min_grade`` (labels path only) is the binary-metrics strictness: only chunks with gold
    grade >= min_grade count as relevant. ``source=urls`` measures each case's ground-truth URLs
    via the ``contains_urls`` evaluator captures of an eval run (``run_id``, default most-recent).
    Returns ``available=False`` when there is nothing to measure against.
    """
    if source == "labels":
        ids = dataset_ids or ([dataset_id] if dataset_id else None)
        datasets = await resolve_datasets(db, project, ids)
        return await compute_overall_labels_metrics(
            db, project, datasets, gold_source, refresh, min_grade
        )

    # Risk slice per test case, for the per-slice metric breakdown on the URLs path.
    slice_by_test = await resolve_slices(db, project)
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
    # Prefer the point-in-time snapshot stored when the run finished; recompute only on refresh or
    # for older runs that predate the snapshot.
    if run.retrieval_summary and not refresh:
        return RetrievalRunMetrics.model_validate(run.retrieval_summary)
    results = (
        await db.execute(select(EvalResult).where(EvalResult.run_id == run.id))
    ).scalars().all()
    negatives = await negative_test_ids(db, project_id=project.id)
    return aggregate_run_retrieval_metrics(run, results, slice_by_test, exclude_test_ids=negatives)


@router.get("/retrieval-metrics/by-stage", response_model=ByStageMetricsResponse)
async def get_retrieval_metrics_by_stage(
    dataset_id: UUID | None = None,
    dataset_ids: list[UUID] | None = Query(None),
    gold_source: str = "human",
    min_grade: int = Query(1, ge=1, le=3),
    refresh: bool = False,
    include_agent: bool = False,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Deterministic retrieval metrics per pipeline stage (sparse/dense/RRF/reranked/agentic).

    For each case (pooled across ``dataset_ids``; ``dataset_id`` is the single-dataset alias) we
    assemble the candidate pool (which records each chunk's rank per head), reconstruct each
    stage's ranked list, and score it against the chunk-label gold (``gold_source`` = human | ai |
    both, binarized at ``min_grade``). Stages are compared side by side, with a per-case grid.
    ``include_agent`` adds the configured custom-agent endpoint as an extra stage.
    """
    ids = dataset_ids or ([dataset_id] if dataset_id else None)
    datasets = await resolve_datasets(db, project, ids)
    return await compute_by_stage_metrics(
        db, project, datasets, gold_source, refresh, min_grade, include_agent
    )


@router.post("/retrieval-metrics/compute", response_model=RetrievalComputeJob)
async def start_retrieval_metrics_compute(
    body: RetrievalComputeStart,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Start a detached labels-path metrics compute and return the job to poll.

    The live probe + embedding work runs in a background task that writes its result into the Redis
    metrics cache; the panel then reads it via the plain ``retrieval-metrics`` endpoint. Keeping the
    compute off the request means a reload / proxy timeout can't reset the socket mid-flight (which
    surfaced as a phantom 500). ``view`` is ``overall`` (default) or ``byStage``.
    """
    view = "byStage" if body.view == "byStage" else "overall"
    job = RetrievalMetricsJob(
        project_id=project.id,
        created_by=user.id,
        view=view,
        gold_source=body.gold_source,
        min_grade=body.min_grade,
        dataset_ids=list(body.dataset_ids or []),
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    task = asyncio.create_task(
        run_metrics_job(job.id, refresh=body.refresh, include_agent=body.include_agent)
    )
    _metrics_jobs[job.id] = task
    task.add_done_callback(lambda _t, jid=job.id: _metrics_jobs.pop(jid, None))
    return _job_view(job)


@router.get("/retrieval-metrics/compute/{job_id}", response_model=RetrievalComputeJob)
async def get_retrieval_metrics_compute(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Poll a compute job's status; carries the error + traceback (debug) when it failed."""
    job = await db.get(RetrievalMetricsJob, job_id)
    if job is None or job.project_id != project.id:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Compute job not found"}},
        )
    return _job_view(job)


@router.get("/targets", response_model=RetrievalTargets)
async def get_targets(project: Project = Depends(get_current_project)):
    """The project's retrieval-metric targets, merged over defaults."""
    return RetrievalTargets(**get_retrieval_targets(project.settings))


@router.put(
    "/targets",
    response_model=RetrievalTargets,
    dependencies=[require_write("evaluate", "pipeline")],
)
async def update_targets(
    body: RetrievalTargets,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Save the project's retrieval-metric targets (clamped to [0, 1])."""
    clean = sanitize_targets(body.model_dump())
    # Replace settings with a new dict so SQLAlchemy detects the JSONB change.
    project.settings = {**(project.settings or {}), TARGETS_SETTINGS_KEY: clean}
    await db.flush()
    return RetrievalTargets(**clean)
