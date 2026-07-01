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
from app.routers.chunk_labels._helpers import (
    _dataset_case_agentic_queries,
    assemble_case_pool,
)
from app.schemas.retrieval import (
    ByStageMetricsResponse,
    RetrievalPipelineResponse,
    RetrievalRunMetrics,
    RetrievalTargets,
)
from app.services.analysis_llm import merge_llm_settings
from app.services.chunk_agreement import resolve_gold
from app.services.query_embedding import build_query_embedder
from app.services.retrieval_config import get_rag_span_names
from app.services.retrieval_metrics_aggregate import (
    AGG_KS,
    STAGE_LABELS,
    aggregate_retrieval_metrics_from_labels,
    aggregate_run_retrieval_metrics,
    build_by_stage_metrics,
)
from app.services.retrieval_metrics_cache import get_cached, result_cache_key, store
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
    dataset_ids: list[UUID] | None = Query(None),
    source: str = "urls",
    refresh: bool = False,
    gold_source: str = "human",
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Retrieval-quality metrics (recall@k / precision@k / MRR / nDCG).

    ``source=labels`` measures pooled chunk labels against a *live retrieval probe* of the
    connected index, over one or more datasets' test cases (``dataset_ids``; ``dataset_id`` is the
    single-dataset alias; default most-recent). This is the data-labeling lens and needs no eval
    run. ``source=urls`` measures each case's ground-truth URLs via the ``contains_urls`` evaluator
    captures of an eval run (``run_id``, default most-recent). Returns ``available=False`` when
    there is nothing to measure against.
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
        ids = dataset_ids or ([dataset_id] if dataset_id else None)
        return await _labels_metrics(db, project, ids, slice_by_test, refresh, gold_source)

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
    return aggregate_run_retrieval_metrics(run, results, slice_by_test)


async def _resolve_project_gold(
    db: AsyncSession, project: Project, gold_source: str
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, dict[str, int]]]:
    """Resolve gold chunk relevance for the project from the chosen annotator source.

    ``gold_source`` picks whose labels count: ``human`` (default, human labels only), ``ai`` (the
    AI judge's labels only), or ``both`` (as independent annotators). Human labels carry
    ``annotator=None`` (keyed by user); the AI judge carries ``annotator="AI"``. Adjudicated gold
    overrides always win. Returns ``(relevant_by_test, nonrelevant_by_test, grade_by_test)``.
    """
    # Select only the scalar fields gold resolution needs — not full ORM rows. The label table
    # carries Text snapshots (content_preview/url/title) that would otherwise load the whole
    # project's judged-chunk text into memory on every metrics request.
    labels = (
        await db.execute(
            select(
                ChunkRelevanceLabel.test_id,
                ChunkRelevanceLabel.chunk_id,
                ChunkRelevanceLabel.relevance,
                ChunkRelevanceLabel.annotator,
                ChunkRelevanceLabel.labeled_by,
            ).where(ChunkRelevanceLabel.project_id == project.id)
        )
    ).all()
    golds = (
        await db.execute(
            select(
                ChunkGoldLabel.test_id, ChunkGoldLabel.chunk_id, ChunkGoldLabel.relevance
            ).where(ChunkGoldLabel.project_id == project.id)
        )
    ).all()
    overrides = {(test_id, chunk_id): relevance for test_id, chunk_id, relevance in golds}

    def _included(annotator: str | None) -> bool:
        is_ai = annotator is not None
        if gold_source == "ai":
            return is_ai
        if gold_source == "both":
            return True
        return not is_ai  # "human"

    return resolve_gold(
        (
            (test_id, chunk_id, relevance, labeled_by if annotator is None else annotator)
            for test_id, chunk_id, relevance, annotator, labeled_by in labels
            if _included(annotator)
        ),
        overrides,
    )


async def _resolve_datasets(
    db: AsyncSession, project: Project, dataset_ids: list[UUID] | None
) -> list[TestDataset]:
    """The selected datasets (newest first), or the single most-recent one when none are given."""
    base = [TestDataset.project_id == project.id]
    if dataset_ids:
        rows = (
            await db.execute(
                select(TestDataset)
                .where(*base, TestDataset.id.in_(dataset_ids))
                .order_by(TestDataset.updated_at.desc())
            )
        ).scalars().all()
        return list(rows)
    row = (
        await db.execute(
            select(TestDataset).where(*base).order_by(TestDataset.updated_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return [row] if row is not None else []


def _datasets_label(datasets: list[TestDataset]) -> tuple[str | None, str]:
    """(id, name) for the metrics header: the dataset's own when one, else an "N datasets" label."""
    if len(datasets) == 1:
        return str(datasets[0].id), datasets[0].name
    return None, f"{len(datasets)} datasets"


async def _dataset_cases(
    db: AsyncSession, dataset_ids: list[UUID]
) -> list[tuple[str, str | None]]:
    """(test_id, prompt) across the given datasets, deduped by test_id (labels carry over)."""
    rows = (
        await db.execute(
            select(TestCase.test_id, TestCase.prompt).where(TestCase.dataset_id.in_(dataset_ids))
        )
    ).all()
    seen: set[str] = set()
    cases: list[tuple[str, str | None]] = []
    for tid, prompt in rows:
        if tid not in seen:
            seen.add(tid)
            cases.append((tid, prompt))
    return cases


async def _labels_metrics(
    db: AsyncSession,
    project: Project,
    dataset_ids: list[UUID] | None,
    slice_by_test: dict[str, str],
    refresh: bool,
    gold_source: str = "human",
) -> RetrievalRunMetrics:
    """Labels-vs-live-probe metrics over one or more datasets' cases.

    ``gold_source`` selects which annotators' chunk labels resolve the gold: ``human`` (default,
    human labels only), ``ai`` (the AI judge's labels only), or ``both`` (union — AI counts as one
    more annotator). Gold overrides (adjudicated) always win regardless. Multiple datasets pool
    their cases (deduped by test_id) and are aggregated together.
    """
    datasets = await _resolve_datasets(db, project, dataset_ids)
    if not datasets:
        return RetrievalRunMetrics(available=False, ks=list(AGG_KS))

    # Serve a previously computed result unless the caller forces a recompute. Keyed by the exact
    # dataset set + gold source, so pressing Compute on the same settings is instant.
    cache_key = result_cache_key(project.id, "overall", [d.id for d in datasets], gold_source)
    if not refresh:
        cached = await get_cached(cache_key, RetrievalRunMetrics)
        if cached is not None:
            return cached

    cases = await _dataset_cases(db, [d.id for d in datasets])
    ds_id, ds_name = _datasets_label(datasets)

    relevant_by_test, nonrelevant_by_test, grade_by_test = await _resolve_project_gold(
        db, project, gold_source
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
            run_id=ds_id,
            run_name=ds_name,
            total_cases=len(cases),
            ks=list(AGG_KS),
        )

    k = max(AGG_KS)
    provider = build_index_provider(provider_row)
    sem = asyncio.Semaphore(_PROBE_CONCURRENCY)
    embed_settings = merge_llm_settings(project.settings, None)
    # Build the embedder once and reuse it across every probe. The probe embeds lazily on cache
    # miss only, so a warm cache does zero embedding-API work.
    embedder = build_query_embedder(embed_settings)

    async def _probe(test_id: str, query: str) -> tuple[str, list[str]]:
        async with sem:
            ids = await cached_probe_chunk_ids(
                provider, project.id, test_id, str(query or ""), k,
                embedder=embedder, refresh=refresh,
            )
            return test_id, ids

    try:
        # Only probe cases that have a gold relevant set (others are dropped by the aggregator).
        probed = await asyncio.gather(
            *(_probe(tid, q) for tid, q in cases if relevant_by_test.get(tid))
        )
    finally:
        await provider.aclose()
        if embedder is not None:
            await embedder.aclose()
    retrieved_by_test = dict(probed)

    result = aggregate_retrieval_metrics_from_labels(
        cases,
        retrieved_by_test,
        relevant_by_test,
        nonrelevant_by_test,
        slice_by_test,
        grade_by_test=grade_by_test,
        dataset_id=ds_id,
        dataset_name=ds_name,
    )
    # Only cache a result that actually measured something; caching an "unavailable" (no gold / no
    # index) result would hide labeling or index-connection progress for the whole TTL.
    if result.available:
        return await store(cache_key, result)
    return result


@router.get("/retrieval-metrics/by-stage", response_model=ByStageMetricsResponse)
async def get_retrieval_metrics_by_stage(
    dataset_id: UUID | None = None,
    dataset_ids: list[UUID] | None = Query(None),
    gold_source: str = "human",
    refresh: bool = False,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Deterministic retrieval metrics per pipeline stage (sparse/dense/RRF/reranked/agentic).

    For each case (pooled across ``dataset_ids``; ``dataset_id`` is the single-dataset alias) we
    assemble the candidate pool (which records each chunk's rank per head), reconstruct each
    stage's ranked list, and score it against the chunk-label gold (``gold_source`` = human | ai |
    both). Stages are compared side by side, with a per-case grid.
    """
    ids = dataset_ids or ([dataset_id] if dataset_id else None)
    datasets = await _resolve_datasets(db, project, ids)
    if not datasets:
        return ByStageMetricsResponse(available=False, gold_source=gold_source, ks=list(AGG_KS))
    dataset_uuids = [d.id for d in datasets]

    cache_key = result_cache_key(project.id, "by-stage", dataset_uuids, gold_source)
    if not refresh:
        cached = await get_cached(cache_key, ByStageMetricsResponse)
        if cached is not None:
            return cached

    ds_id, ds_name = _datasets_label(datasets)
    cases = await _dataset_cases(db, dataset_uuids)

    relevant_by_test, nonrelevant_by_test, grade_by_test = await _resolve_project_gold(
        db, project, gold_source
    )
    slice_rows = (
        await db.execute(
            select(TestCaseLabelingStatus.test_id, TestCaseLabelingStatus.slice).where(
                TestCaseLabelingStatus.project_id == project.id,
                TestCaseLabelingStatus.slice.is_not(None),
            )
        )
    ).all()
    slice_by_test = {tid: s for tid, s in slice_rows}

    # Only pool cases that have gold (others are dropped by the aggregator anyway).
    todo = [(tid, q) for tid, q in cases if relevant_by_test.get(tid)]
    heads = [head for head, _ in STAGE_LABELS]
    retrieved_by_stage: dict[str, dict[str, list[str]]] = {h: {} for h in heads}
    sem = asyncio.Semaphore(_PROBE_CONCURRENCY)

    async def _pool_case(test_id: str, query: str) -> None:
        async with sem:
            # A test_id lives in one of the selected datasets; use the first with planned queries.
            agentic: list[str] = []
            for dsid in dataset_uuids:
                agentic = await _dataset_case_agentic_queries(db, dsid, test_id)
                if agentic:
                    break
            pool, _computed, connected = await assemble_case_pool(
                db, project, test_id, str(query or ""), agentic_queries=agentic, refresh=refresh
            )
            if not connected:
                return
            for head in heads:
                ranked = sorted(
                    (c for c in pool.chunks if head in c.ranks), key=lambda c: c.ranks[head]
                )
                if ranked:
                    retrieved_by_stage[head][test_id] = [c.chunk_id for c in ranked]

    await asyncio.gather(*(_pool_case(tid, q) for tid, q in todo))

    stages, case_rows_out, evaluated = build_by_stage_metrics(
        cases,
        retrieved_by_stage,
        relevant_by_test,
        nonrelevant_by_test,
        grade_by_test,
        slice_by_test,
    )
    result = ByStageMetricsResponse(
        available=evaluated > 0,
        dataset_id=ds_id,
        dataset_name=ds_name,
        gold_source=gold_source,
        ks=list(AGG_KS),
        total_cases=len(cases),
        evaluated_cases=evaluated,
        stages=stages,
        cases=case_rows_out,
    )
    if result.available:
        return await store(cache_key, result)
    return result


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
