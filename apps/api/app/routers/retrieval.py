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

from app.auth import get_current_project, require_section, require_write
from app.db import get_db
from app.index_providers.registry import build_index_provider
from app.models.chunk_labels import (
    ChunkGoldLabel,
    ChunkRelevanceLabel,
    TestCaseLabelingStatus,
)
from app.models.datasets import TestCase, TestDataset
from app.models.evaluations import EvalResult, EvalRun
from app.models.index_providers import IndexProvider
from app.models.models import Integration, Trace
from app.models.project import Project
from app.schemas.retrieval import (
    RetrievalPipelineResponse,
    RetrievalRunMetrics,
    RetrievalTargets,
)
from app.services.chunk_agreement import resolve_gold
from app.services.retrieval_config import get_rag_span_names
from app.services.retrieval_metrics_aggregate import (
    AGG_KS,
    aggregate_retrieval_metrics_from_labels,
    aggregate_run_retrieval_metrics,
)
from app.services.retrieval_pipeline_aggregate import build_retrieval_pipeline_aggregate
from app.services.retrieval_probe import cached_probe_chunk_ids
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


# Bound concurrent index probes so computing labels-metrics over a big dataset can't hammer
# the index. Matches the labeling page's per-case pool concurrency.
_PROBE_CONCURRENCY = 4


@router.get("/retrieval-metrics", response_model=RetrievalRunMetrics)
async def get_retrieval_metrics(
    run_id: UUID | None = None,
    dataset_id: UUID | None = None,
    source: str = "urls",
    refresh: bool = False,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Retrieval-quality metrics (recall@k / precision@k / MRR / nDCG).

    ``source=labels`` measures pooled human chunk labels against a *live retrieval probe* of the
    connected index, over a dataset's test cases (``dataset_id``, default most-recent). This is
    the data-labeling lens and needs no eval run. ``source=urls`` measures each case's
    ground-truth URLs via the ``contains_urls`` evaluator captures of an eval run (``run_id``,
    default most-recent). Returns ``available=False`` when there is nothing to measure against.
    """
    # Risk slice per test case, for the per-slice metric breakdown (shared by both sources).
    statuses = (
        await db.execute(
            select(TestCaseLabelingStatus.test_id, TestCaseLabelingStatus.slice).where(
                TestCaseLabelingStatus.project_id == project.id,
                TestCaseLabelingStatus.slice.is_not(None),
            )
        )
    ).all()
    slice_by_test = {test_id: slice_ for test_id, slice_ in statuses}

    if source == "labels":
        return await _labels_metrics(db, project, dataset_id, slice_by_test, refresh)

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
    return aggregate_run_retrieval_metrics(run, results, slice_by_test)


async def _labels_metrics(
    db: AsyncSession,
    project: Project,
    dataset_id: UUID | None,
    slice_by_test: dict[str, str],
    refresh: bool,
) -> RetrievalRunMetrics:
    """Labels-vs-live-probe metrics over a dataset's cases."""
    ds_filter = [TestDataset.project_id == project.id]
    if dataset_id is not None:
        ds_filter.append(TestDataset.id == dataset_id)
    dataset = (
        await db.execute(
            select(TestDataset).where(*ds_filter).order_by(TestDataset.updated_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if dataset is None:
        return RetrievalRunMetrics(available=False, ks=list(AGG_KS))

    case_rows = (
        await db.execute(
            select(TestCase.test_id, TestCase.prompt).where(TestCase.dataset_id == dataset.id)
        )
    ).all()
    cases = [(tid, prompt) for tid, prompt in case_rows]

    # Resolve per-annotator labels into a single gold verdict per chunk (majority vote / adjudicated
    # override). AI judge labels (annotator set) are a second opinion only — excluded from the gold.
    labels = (
        await db.execute(
            select(ChunkRelevanceLabel).where(ChunkRelevanceLabel.project_id == project.id)
        )
    ).scalars().all()
    golds = (
        await db.execute(select(ChunkGoldLabel).where(ChunkGoldLabel.project_id == project.id))
    ).scalars().all()
    overrides = {(g.test_id, g.chunk_id): g.relevance for g in golds}
    relevant_by_test, nonrelevant_by_test, grade_by_test = resolve_gold(
        (
            (lbl.test_id, lbl.chunk_id, lbl.relevance, lbl.labeled_by)
            for lbl in labels
            if lbl.annotator is None
        ),
        overrides,
    )

    # Probe the connected index live for what "the system" retrieves per case. No index → no
    # system retrieval to measure against.
    provider_row = (
        await db.execute(
            select(IndexProvider)
            .where(IndexProvider.project_id == project.id)
            .order_by(IndexProvider.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if provider_row is None:
        return RetrievalRunMetrics(
            available=False,
            run_id=str(dataset.id),
            run_name=dataset.name,
            total_cases=len(cases),
            ks=list(AGG_KS),
        )

    k = max(AGG_KS)
    provider = build_index_provider(provider_row)
    sem = asyncio.Semaphore(_PROBE_CONCURRENCY)

    async def _probe(test_id: str, query: str) -> tuple[str, list[str]]:
        async with sem:
            ids = await cached_probe_chunk_ids(
                provider, project.id, test_id, str(query or ""), k, refresh=refresh
            )
            return test_id, ids

    try:
        # Only probe cases that have a gold relevant set (others are dropped by the aggregator).
        probed = await asyncio.gather(
            *(_probe(tid, q) for tid, q in cases if relevant_by_test.get(tid))
        )
    finally:
        await provider.aclose()
    retrieved_by_test = dict(probed)

    return aggregate_retrieval_metrics_from_labels(
        cases,
        retrieved_by_test,
        relevant_by_test,
        nonrelevant_by_test,
        slice_by_test,
        grade_by_test=grade_by_test,
        dataset_id=str(dataset.id),
        dataset_name=dataset.name,
    )


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
