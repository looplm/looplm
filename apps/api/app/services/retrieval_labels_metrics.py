"""Labels-vs-live-probe retrieval metrics computation.

The chunk-label retrieval quality (recall/precision/MRR/nDCG, bpref, cNDCG, and the per-stage
breakdown) is measured by pooling human/AI chunk relevance labels and comparing them to what the
connected index retrieves live per case. This module holds that computation so both the read
endpoints (``routers/retrieval.py``) and the run-history snapshots (``routers/retrieval_runs.py``)
share one code path. Results are cached in Redis (see ``retrieval_metrics_cache``); a warm cache
serves without touching the index or embedding API.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.index_providers.registry import build_index_provider
from app.models.chunk_labels import TestCaseLabelingStatus
from app.models.datasets import TestCase, TestDataset
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.routers.chunk_labels._helpers import (
    _dataset_case_agentic_queries,
    assemble_case_pool,
)
from app.schemas.retrieval import ByStageMetricsResponse, RetrievalRunMetrics
from app.services.analysis_llm import merge_llm_settings
from app.services.chunk_pool import AGENTIC_RERANK_DEPTH
from app.services.chunk_gold import resolve_project_gold
from app.services.query_embedding import build_query_embedder
from app.services.retrieval_metrics_aggregate import (
    AGG_KS,
    STAGE_LABELS,
    aggregate_retrieval_metrics_from_labels,
    build_by_stage_metrics,
    compute_rerank_threshold_sweep,
)
from app.services.retrieval_metrics_cache import get_cached, result_cache_key, store
from app.services.retrieval_probe import cached_probe_chunk_ids

# Bound concurrent index probes so computing labels-metrics over a big dataset can't hammer the
# index. Matches the labeling page's per-case pool concurrency.
PROBE_CONCURRENCY = 4


async def resolve_datasets(
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


def datasets_label(datasets: list[TestDataset]) -> tuple[str | None, str]:
    """(id, name) for the metrics header: the dataset's own when one, else an "N datasets" label."""
    if len(datasets) == 1:
        return str(datasets[0].id), datasets[0].name
    return None, f"{len(datasets)} datasets"


async def resolve_slices(db: AsyncSession, project: Project) -> dict[str, str]:
    """Risk slice per test case (for the per-slice metric breakdown); unset cases are omitted."""
    rows = (
        await db.execute(
            select(TestCaseLabelingStatus.test_id, TestCaseLabelingStatus.slice).where(
                TestCaseLabelingStatus.project_id == project.id,
                TestCaseLabelingStatus.slice.is_not(None),
            )
        )
    ).all()
    return {test_id: slice_ for test_id, slice_ in rows}


async def dataset_cases(
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


async def resolve_case_datasets(db: AsyncSession, dataset_ids: list[UUID]) -> dict[str, str]:
    """test_id → dataset id (first dataset containing it), so the UI can link each case."""
    rows = (
        await db.execute(
            select(TestCase.test_id, TestCase.dataset_id).where(
                TestCase.dataset_id.in_(dataset_ids)
            )
        )
    ).all()
    out: dict[str, str] = {}
    for tid, dsid in rows:
        out.setdefault(tid, str(dsid))
    return out


async def compute_overall_labels_metrics(
    db: AsyncSession,
    project: Project,
    datasets: list[TestDataset],
    gold_source: str,
    refresh: bool,
    min_grade: int = 1,
) -> RetrievalRunMetrics:
    """Labels-vs-live-probe overall metrics over the given datasets' cases.

    ``gold_source`` selects which annotators' chunk labels resolve the gold: ``human`` (default),
    ``ai`` (the AI judge only), or ``both`` (union). Gold overrides (adjudicated) always win.
    ``min_grade`` (1..3) is the binary-metrics strictness: only chunks with gold grade >=
    min_grade count as relevant; lower relevant grades become unjudged (graded nDCG is
    unaffected). Multiple datasets pool their cases (deduped by test_id) and aggregate together.
    Cached in Redis keyed by dataset set + gold source + min grade; a warm cache does no
    index/embedding work.
    """
    if not datasets:
        return RetrievalRunMetrics(available=False, ks=list(AGG_KS))

    dataset_uuids = [d.id for d in datasets]
    cache_key = result_cache_key(project.id, "overall", dataset_uuids, gold_source, min_grade)
    if not refresh:
        cached = await get_cached(cache_key, RetrievalRunMetrics)
        if cached is not None:
            return cached

    cases = await dataset_cases(db, dataset_uuids)
    ds_id, ds_name = datasets_label(datasets)

    relevant_by_test, nonrelevant_by_test, grade_by_test = await resolve_project_gold(
        db, project, gold_source, min_grade
    )
    slice_by_test = await resolve_slices(db, project)

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
    sem = asyncio.Semaphore(PROBE_CONCURRENCY)
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
        dataset_by_test=await resolve_case_datasets(db, dataset_uuids),
    )
    # Only cache a result that actually measured something; caching an "unavailable" (no gold / no
    # index) result would hide labeling or index-connection progress for the whole TTL.
    if result.available:
        return await store(cache_key, result)
    return result


async def compute_by_stage_metrics(
    db: AsyncSession,
    project: Project,
    datasets: list[TestDataset],
    gold_source: str,
    refresh: bool,
    min_grade: int = 1,
) -> ByStageMetricsResponse:
    """Deterministic per-stage retrieval metrics (sparse/dense/RRF/reranked/agentic) vs gold.

    For each case we assemble the candidate pool (which records each chunk's rank per head),
    reconstruct each stage's ranked list, and score it against the chunk-label gold. Cached in
    Redis keyed by dataset set + gold source + min grade.
    """
    if not datasets:
        return ByStageMetricsResponse(
            available=False, gold_source=gold_source, min_grade=min_grade, ks=list(AGG_KS)
        )

    dataset_uuids = [d.id for d in datasets]
    cache_key = result_cache_key(project.id, "by-stage", dataset_uuids, gold_source, min_grade)
    if not refresh:
        cached = await get_cached(cache_key, ByStageMetricsResponse)
        if cached is not None:
            return cached

    ds_id, ds_name = datasets_label(datasets)
    cases = await dataset_cases(db, dataset_uuids)

    relevant_by_test, nonrelevant_by_test, grade_by_test = await resolve_project_gold(
        db, project, gold_source, min_grade
    )
    slice_by_test = await resolve_slices(db, project)

    # Only pool cases that have gold (others are dropped by the aggregator anyway).
    todo = [(tid, q) for tid, q in cases if relevant_by_test.get(tid)]
    heads = [head for head, _ in STAGE_LABELS]
    retrieved_by_stage: dict[str, dict[str, list[str]]] = {h: {} for h in heads}
    # test_id -> [(chunk_id, rerankerScore)] for the agentic-rerank stage, feeding the threshold sweep.
    rerank_scores_by_test: dict[str, list[tuple[str, float]]] = {}
    sem = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def _pool_case(test_id: str, query: str) -> None:
        async with sem:
            # A test_id lives in one of the selected datasets; use the first with planned queries.
            agentic: list[str] = []
            for dsid in dataset_uuids:
                agentic = await _dataset_case_agentic_queries(db, dsid, test_id)
                if agentic:
                    break
            pool, _computed, connected = await assemble_case_pool(
                db,
                project,
                test_id,
                str(query or ""),
                agentic_queries=agentic,
                rerank_depth=AGENTIC_RERANK_DEPTH,
                refresh=refresh,
            )
            if not connected:
                return
            for head in heads:
                if head == "agentic_rerank":
                    # Ordered by semantic-reranker score (desc), not by a positional rank.
                    ranked = sorted(
                        (c for c in pool.chunks if c.agentic_rerank_score is not None),
                        key=lambda c: c.agentic_rerank_score,
                        reverse=True,
                    )
                else:
                    ranked = sorted(
                        (c for c in pool.chunks if head in c.ranks), key=lambda c: c.ranks[head]
                    )
                if ranked:
                    retrieved_by_stage[head][test_id] = [c.chunk_id for c in ranked]
                    if head == "agentic_rerank":
                        rerank_scores_by_test[test_id] = [
                            (c.chunk_id, c.agentic_rerank_score) for c in ranked
                        ]

    await asyncio.gather(*(_pool_case(tid, q) for tid, q in todo))

    stages, case_rows_out, evaluated = build_by_stage_metrics(
        cases,
        retrieved_by_stage,
        relevant_by_test,
        nonrelevant_by_test,
        grade_by_test,
        slice_by_test,
        dataset_by_test=await resolve_case_datasets(db, dataset_uuids),
    )
    # Attach the score-threshold sweep to the agentic-rerank stage so the UI can offer a variable-k
    # (rerankerScore) cutoff without another compute.
    sweep = compute_rerank_threshold_sweep(rerank_scores_by_test, relevant_by_test)
    for stage in stages:
        if stage.stage == "agentic_rerank":
            stage.threshold_sweep = sweep
            break
    result = ByStageMetricsResponse(
        available=evaluated > 0,
        dataset_id=ds_id,
        dataset_name=ds_name,
        gold_source=gold_source,
        min_grade=min_grade,
        ks=list(AGG_KS),
        total_cases=len(cases),
        evaluated_cases=evaluated,
        stages=stages,
        cases=case_rows_out,
    )
    if result.available:
        return await store(cache_key, result)
    return result


async def get_cached_by_stage(
    project: Project, dataset_ids: list[UUID], gold_source: str, min_grade: int = 1
) -> ByStageMetricsResponse | None:
    """Return a previously cached by-stage result for these settings, or None (no recompute)."""
    key = result_cache_key(project.id, "by-stage", dataset_ids, gold_source, min_grade)
    return await get_cached(key, ByStageMetricsResponse)
