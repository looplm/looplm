"""Chunk/metadata quality endpoints.

The read-side counterpart to the index explorer and source registry: samples a
provider's index and scores the quality of the indexed chunks themselves
(size/consistency, duplication/overlap, metadata completeness, parser quality).

Lives under the same permission page as those views ("data-sources").
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section, require_write
from app.db import async_session, get_db
from app.models.chunk_quality import ChunkQualityRun
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.routers.chunk_quality_worker import run_chunk_quality_analysis
from app.schemas.chunk_quality import (
    ChunkQualityRunConfig,
    ChunkQualityRunCreateResponse,
    ChunkQualityRunRequest,
    ChunkQualityRunResponse,
    ChunkQualityRunSummary,
    ChunkQualityRunSummaryListResponse,
)

# results["families"][family][metric] lifted into each run summary so the runs
# list doubles as the cross-run trend series without shipping full results.
_HEADLINE_METRICS = (
    ("boundary", "bad_end_pct", "boundary_bad_end_pct"),
    ("boundary", "bad_start_pct", "boundary_bad_start_pct"),
    ("standalone", "dependent_pct", "standalone_dependent_pct"),
    ("cohesion", "high_spread_pct", "cohesion_high_spread_pct"),
    ("retrieval_frequency", "dead_pct", "retrieval_dead_pct"),
    ("claim_boundary", "cross_boundary_pct", "claim_cross_boundary_pct"),
)


def _headline(results: dict | None) -> dict[str, float | None]:
    families = (results or {}).get("families") or {}
    out: dict[str, float | None] = {}
    for family, metric, key in _HEADLINE_METRICS:
        fam = families.get(family) or {}
        value = fam.get(metric) if fam.get("available") else None
        out[key] = float(value) if isinstance(value, (int, float)) else None
    return out

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/chunk-quality",
    tags=["chunk-quality"],
    dependencies=[require_section("observe", "data-sources")],
)

# Keep background tasks referenced so they aren't garbage-collected mid-run.
_tasks: dict[UUID, asyncio.Task] = {}


def _not_found(what: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail={"error": {"code": "NOT_FOUND", "message": f"{what} not found"}}
    )


async def _provider_or_404(db: AsyncSession, provider_id: UUID, project: Project) -> IndexProvider:
    provider = (
        await db.execute(
            select(IndexProvider).where(
                IndexProvider.id == provider_id, IndexProvider.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if provider is None:
        raise _not_found("Index provider")
    return provider


@router.post(
    "/runs",
    response_model=ChunkQualityRunCreateResponse,
    status_code=202,
    dependencies=[require_write("observe", "data-sources")],
)
async def create_run(
    body: ChunkQualityRunRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    await _provider_or_404(db, body.provider_id, project)
    config = (body.config or ChunkQualityRunConfig()).model_dump(mode="json")
    run = ChunkQualityRun(
        project_id=project.id,
        provider_id=body.provider_id,
        status="pending",
        sample_size=body.sample_size,
        config=config,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    run_id = run.id
    # Commit before spawning: the worker opens its own session and must see the row.
    await db.commit()

    task = asyncio.create_task(
        run_chunk_quality_analysis(
            run_id=run_id,
            project_id=project.id,
            provider_id=body.provider_id,
            sample_size=body.sample_size,
            config=config,
            db_factory=async_session,
        )
    )
    _tasks[run_id] = task
    task.add_done_callback(lambda _t, rid=run_id: _tasks.pop(rid, None))
    return ChunkQualityRunCreateResponse(run_id=run_id, status="pending")


@router.post(
    "/runs/{run_id}/cancel",
    response_model=ChunkQualityRunCreateResponse,
    dependencies=[require_write("observe", "data-sources")],
)
async def cancel_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Stop a pending/running analysis.

    Flips the row to 'cancelled' first (so a worker that survives the task
    cancellation cannot overwrite it), then cancels the in-process task.
    Interim results persisted by already-finished passes are kept.
    """
    run = (
        await db.execute(
            select(ChunkQualityRun).where(
                ChunkQualityRun.id == run_id, ChunkQualityRun.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise _not_found("Chunk quality run")
    if run.status not in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "NOT_RUNNING", "message": "Run is not in progress"}},
        )
    run.status = "cancelled"
    run.stage = None
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()

    task = _tasks.get(run_id)
    if task is not None:
        task.cancel()
    return ChunkQualityRunCreateResponse(run_id=run_id, status="cancelled")


def _summary_from_run(run: ChunkQualityRun) -> ChunkQualityRunSummary:
    summary = (run.results or {}).get("summary", {})
    return ChunkQualityRunSummary(
        id=run.id,
        provider_id=run.provider_id,
        status=run.status,
        stage=run.stage,
        sample_size=run.sample_size,
        total_docs=run.total_docs,
        processed=run.processed,
        score=summary.get("score"),
        critical=int(summary.get("critical") or 0),
        warn=int(summary.get("warn") or 0),
        info=int(summary.get("info") or 0),
        error=run.error,
        created_at=run.created_at,
        completed_at=run.completed_at,
        headline=_headline(run.results),
        config=run.config,
    )


@router.get("/runs", response_model=ChunkQualityRunSummaryListResponse)
async def list_runs(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(ChunkQualityRun)
        .where(
            ChunkQualityRun.project_id == project.id,
            ChunkQualityRun.provider_id == provider_id,
        )
        .order_by(ChunkQualityRun.created_at.desc())
    )
    return ChunkQualityRunSummaryListResponse(
        data=[_summary_from_run(r) for r in result.scalars().all()]
    )


@router.get("/runs/{run_id}", response_model=ChunkQualityRunResponse)
async def get_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    run = (
        await db.execute(
            select(ChunkQualityRun).where(
                ChunkQualityRun.id == run_id, ChunkQualityRun.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise _not_found("Chunk quality run")
    return run
