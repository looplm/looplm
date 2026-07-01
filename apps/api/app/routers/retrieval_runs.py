"""Saved retrieval-run history — durable, annotatable, comparable snapshots (labels path).

Each labels-path computation on the Retrieval page is auto-snapshotted here so retrieval quality
can be tracked over time as the RAG pipeline and index evolve, annotated with metadata, and
compared run to run. Read the accompanying computation service (``retrieval_labels_metrics``) for
how the metric blobs are produced; this router only persists, lists, annotates and deletes them.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section, require_write
from app.db import get_db
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.models.retrieval_runs import RetrievalRun
from app.models.user import User
from app.schemas.retrieval import (
    RetrievalRunCreate,
    RetrievalRunListResponse,
    RetrievalRunMetadataUpdate,
    RetrievalRunRecord,
    RetrievalRunSummary,
)
from app.services.retrieval_labels_metrics import (
    compute_overall_labels_metrics,
    get_cached_by_stage,
    resolve_datasets,
)

router = APIRouter(
    prefix="/api/pipeline/retrieval-runs",
    tags=["retrieval-runs"],
    dependencies=[require_section("evaluate", "pipeline")],
)


def _headline(metrics: dict) -> dict:
    """Extract the max-k headline metrics from a stored RetrievalRunMetrics dump."""
    ks = metrics.get("ks") or []
    max_k = max(ks) if ks else None
    key = str(max_k) if max_k is not None else None

    def at(field: str) -> float | None:
        table = metrics.get(field) or {}
        return table.get(key) if key is not None else None

    return {
        "max_k": max_k,
        "recall": at("recall_at_k"),
        "ndcg": at("ndcg_at_k"),
        "precision": at("precision_at_k"),
        "hit_rate": at("hit_rate_at_k"),
        "mrr": metrics.get("mrr"),
        "bpref": metrics.get("bpref"),
    }


def _summary(run: RetrievalRun) -> RetrievalRunSummary:
    return RetrievalRunSummary(
        id=str(run.id),
        created_at=run.created_at.isoformat() if run.created_at else "",
        gold_source=run.gold_source,
        dataset_ids=list(run.dataset_ids or []),
        dataset_names=list(run.dataset_names or []),
        ks=list(run.ks or []),
        total_cases=run.total_cases,
        evaluated_cases=run.evaluated_cases,
        has_by_stage=run.by_stage is not None,
        name=run.name,
        pipeline_version=run.pipeline_version,
        index_name=run.index_name,
        index_version=run.index_version,
        notes=run.notes,
        **_headline(run.metrics or {}),
    )


def _record(run: RetrievalRun) -> RetrievalRunRecord:
    return RetrievalRunRecord(
        **_summary(run).model_dump(),
        metrics=run.metrics or {},
        by_stage=run.by_stage,
    )


async def _get_owned(db: AsyncSession, project: Project, run_id: UUID) -> RetrievalRun:
    run = (
        await db.execute(
            select(RetrievalRun).where(
                RetrievalRun.id == run_id, RetrievalRun.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Retrieval run not found"}},
        )
    return run


@router.post("", response_model=RetrievalRunRecord, dependencies=[require_write("evaluate", "pipeline")])
async def create_run(
    body: RetrievalRunCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Snapshot the current labels-path metrics as a durable run.

    Computes the overall metrics (served from the warm result cache the panel just populated),
    attaches the by-stage breakdown when one is already cached for the same settings, auto-captures
    the connected index name, and snapshots the dataset names. Rejects when there is nothing to
    measure (no gold / no index connected).
    """
    ids = [UUID(d) for d in body.dataset_ids] or None
    datasets = await resolve_datasets(db, project, ids)
    metrics = await compute_overall_labels_metrics(db, project, datasets, body.gold_source, False)
    if not metrics.available:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "NOTHING_TO_MEASURE",
                    "message": "No chunk-label gold or no connected index to snapshot.",
                }
            },
        )

    by_stage = await get_cached_by_stage(project, [d.id for d in datasets], body.gold_source)

    # Auto-capture the connected index name (Azure config.index_name, else the provider label).
    provider = (
        await db.execute(
            select(IndexProvider)
            .where(IndexProvider.project_id == project.id)
            .order_by(IndexProvider.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    index_name = None
    if provider is not None:
        index_name = (provider.config or {}).get("index_name") or provider.name

    run = RetrievalRun(
        project_id=project.id,
        created_by=user.id,
        gold_source=body.gold_source,
        dataset_ids=[str(d.id) for d in datasets],
        dataset_names=[d.name for d in datasets],
        ks=list(metrics.ks),
        metrics=metrics.model_dump(),
        by_stage=by_stage.model_dump() if by_stage is not None else None,
        total_cases=metrics.total_cases,
        evaluated_cases=metrics.evaluated_cases,
        name=body.name,
        index_name=index_name,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return _record(run)


@router.get("", response_model=RetrievalRunListResponse)
async def list_runs(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """All saved retrieval runs for the project, newest first."""
    rows = (
        await db.execute(
            select(RetrievalRun)
            .where(RetrievalRun.project_id == project.id)
            .order_by(RetrievalRun.created_at.desc())
        )
    ).scalars().all()
    return RetrievalRunListResponse(data=[_summary(r) for r in rows])


@router.get("/{run_id}", response_model=RetrievalRunRecord)
async def get_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Full detail of one saved run (metric blobs included)."""
    return _record(await _get_owned(db, project, run_id))


@router.patch(
    "/{run_id}",
    response_model=RetrievalRunRecord,
    dependencies=[require_write("evaluate", "pipeline")],
)
async def update_run_metadata(
    run_id: UUID,
    body: RetrievalRunMetadataUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Edit a run's metadata (name, pipeline version, index name/version, notes)."""
    run = await _get_owned(db, project, run_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(run, field, value)
    await db.flush()
    await db.refresh(run)
    return _record(run)


@router.delete(
    "/{run_id}",
    dependencies=[require_write("evaluate", "pipeline")],
)
async def delete_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Prune a saved run."""
    run = await _get_owned(db, project, run_id)
    await db.delete(run)
    return {"deleted": True}
