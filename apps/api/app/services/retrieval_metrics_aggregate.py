"""Roll per-case retrieval metrics up to a run-level retrieval-quality summary.

The per-case signal is already captured by the ``contains_urls`` evaluator and persisted
in ``EvalResult.graders[...].details`` (``retrieved_urls`` plus ``found_urls``/
``missing_urls`` = the ground-truth set). This module recomputes the full metric set per
case from those stored URLs — so MRR/nDCG populate even for runs created before they were
wired into the grader — and macro-averages across the cases that carry ground truth.

Macro (per-query) averaging: every query counts equally regardless of how many docs it
expects, which is the standard way to report recall@k across a test set.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk_labels import DEFAULT_SLICE, TestCaseLabelingStatus
from app.models.datasets import TestCase, TestDataset, is_no_retrieval_expected
from app.models.evaluations import EvalResult, EvalRun
from app.schemas.retrieval import (
    ByStageCaseMetrics,
    RerankThresholdPoint,
    RetrievalCaseMetrics,
    RetrievalRunMetrics,
    SliceMetrics,
    StageMetrics,
)
from app.services.failure_pattern import normalize_result_test_id
from app.services.model_resilience import DEGRADED_RETRIEVAL_MODE
from app.services.retrieval_metrics import (
    compute_bpref,
    compute_condensed_ndcg_at_k,
    compute_graded_ndcg_at_k,
    compute_retrieval_metrics,
)

logger = logging.getLogger(__name__)

# Richer k grid than the grader default so the run view can draw a recall curve.
# Extends past 10 because the live probe fetches max(AGG_KS) chunks: deeper cutoffs
# reveal how much recall is left on the table when a query's gold set is larger than 10
# (recall@10 is hard-capped at min(10, #relevant) / #relevant).
AGG_KS: tuple[int, ...] = (1, 3, 5, 10, 20, 50)

# Retrieval pipeline stages, in pipeline order, mapping each pool head to a display label.
STAGE_LABELS: tuple[tuple[str, str], ...] = (
    ("keyword", "Sparse"),
    ("vector", "Dense"),
    ("hybrid", "RRF"),
    ("semantic", "Reranked"),
    ("agentic", "Agentic"),
    ("agentic_rerank", "Agentic + rerank"),
)


# Azure's semantic rerankerScore is a 0-4 scale; sweep it in 0.1 steps so the UI slider can pick a
# score-threshold cutoff from the data. Cheap (set ops over the cases) so a fine grid is fine.
RERANK_THRESHOLDS: tuple[float, ...] = tuple(round(i * 0.1, 1) for i in range(0, 41))


def ranked_chunks_for_head(chunks, head: str):
    """Pool chunks in one retriever head's rank order.

    Every head but ``agentic_rerank`` orders by its positional rank (``ranks[head]``, ascending);
    ``agentic_rerank`` has no positional rank and orders by the semantic reranker score
    (descending). Mirrors how :func:`build_by_stage_metrics` ranks each stage, so a per-case
    diagnosis sees the same ordering the metrics scored.
    """
    if head == "agentic_rerank":
        return sorted(
            (c for c in chunks if c.agentic_rerank_score is not None),
            key=lambda c: c.agentic_rerank_score,
            reverse=True,
        )
    return sorted((c for c in chunks if head in c.ranks), key=lambda c: c.ranks[head])


def compute_rerank_threshold_sweep(
    scores_by_test: dict[str, list[tuple[str, float]]],
    relevant_by_test: dict[str, set[str]],
    thresholds: tuple[float, ...] = RERANK_THRESHOLDS,
) -> list[RerankThresholdPoint]:
    """Macro precision/recall/kept-count as the rerankerScore cutoff sweeps the 0-4 scale.

    For each threshold a case keeps the chunks scoring >= it. Recall and kept-count average over
    every case with gold (an empty keep contributes recall 0); precision averages only over cases
    that kept >= 1 chunk (precision is undefined on an empty keep). Denominator matches the stage's
    macro-average, so the sweep and the @k cards agree on which cases count.
    """
    cases = [(tid, rel) for tid, rel in relevant_by_test.items() if rel]
    n = len(cases)
    if n == 0:
        return []
    points: list[RerankThresholdPoint] = []
    for t in thresholds:
        recalls: list[float] = []
        precisions: list[float] = []
        counts: list[int] = []
        hits = 0
        for tid, rel in cases:
            kept = [cid for cid, sc in scores_by_test.get(tid, []) if sc >= t]
            inter = len(set(kept) & rel)
            recalls.append(inter / len(rel))
            counts.append(len(kept))
            if kept:
                precisions.append(inter / len(kept))
            if inter > 0:
                hits += 1
        points.append(
            RerankThresholdPoint(
                threshold=t,
                precision=round(sum(precisions) / len(precisions), 4) if precisions else None,
                recall=round(sum(recalls) / n, 4),
                hit_rate=round(hits / n, 4),
                avg_retrieved=round(sum(counts) / n, 4),
                evaluated_cases=n,
            )
        )
    return points


def build_by_stage_metrics(
    cases: list[tuple[str, str | None]],
    retrieved_by_stage: dict[str, dict[str, list[str]]],
    relevant_by_test: dict[str, set[str]],
    nonrelevant_by_test: dict[str, set[str]],
    grade_by_test: dict[str, dict[str, int]],
    slice_by_test: dict[str, str],
    ks: tuple[int, ...] = AGG_KS,
    dataset_by_test: dict[str, str] | None = None,
) -> tuple[list[StageMetrics], list[ByStageCaseMetrics], int]:
    """Per-stage metrics + a per-case grid, by scoring each stage's ranking against the gold.

    ``retrieved_by_stage`` maps stage head → {test_id → ranked chunk ids that stage returned}.
    Each stage reuses :func:`aggregate_retrieval_metrics_from_labels`, so the metric math and the
    "drop cases without gold" rule stay identical to the single-ranking view. Returns
    ``(stages, per_case_rows, evaluated_cases)``; the per-case grid carries each stage's recall and
    nDCG at the largest k for the drilldown.
    """
    lk = str(max(ks))
    stages: list[StageMetrics] = []
    # test_id -> {"input", "recall": {stage: v}, "ndcg": {stage: v}}
    per_case: dict[str, dict[str, Any]] = {}
    evaluated = 0
    for head, label in STAGE_LABELS:
        m = aggregate_retrieval_metrics_from_labels(
            cases,
            retrieved_by_stage.get(head, {}),
            relevant_by_test,
            nonrelevant_by_test,
            slice_by_test,
            grade_by_test,
            ks=ks,
            dataset_by_test=dataset_by_test,
        )
        evaluated = max(evaluated, m.evaluated_cases)
        stages.append(
            StageMetrics(
                stage=head,
                label=label,
                evaluated_cases=m.evaluated_cases,
                recall_at_k=m.recall_at_k,
                precision_at_k=m.precision_at_k,
                hit_rate_at_k=m.hit_rate_at_k,
                ndcg_at_k=m.ndcg_at_k,
                mrr=m.mrr,
                metrics=m,
            )
        )
        for c in m.cases:
            slot = per_case.setdefault(c.test_id, {"input": c.input, "recall": {}, "ndcg": {}})
            slot["recall"][head] = (c.recall_at_k or {}).get(lk)
            slot["ndcg"][head] = (c.ndcg_at_k or {}).get(lk)

    rows = [
        ByStageCaseMetrics(
            test_id=tid,
            input=slot["input"],
            recall_by_stage=slot["recall"],
            ndcg_by_stage=slot["ndcg"],
        )
        for tid, slot in per_case.items()
    ]
    # Worst reranked recall first, so the cases the final ranking struggles on lead the drilldown.
    rows.sort(key=lambda r: (r.recall_by_stage.get("semantic") is None, r.recall_by_stage.get("semantic") or 0.0))
    return stages, rows, evaluated


async def negative_test_ids(
    db: AsyncSession,
    *,
    project_id: UUID | None = None,
    dataset_ids: list[UUID] | None = None,
) -> set[str]:
    """test_ids tagged no-retrieval-expected: negative cases whose queries must retrieve nothing.

    They carry no meaningful retrieval ground truth, so every metrics path drops them before
    aggregation (and reports the count). Tag membership is checked in Python, not SQL, so the
    JSONB column stays portable to the SQLite test setup.
    """
    stmt = select(TestCase.test_id, TestCase.tags)
    if dataset_ids is not None:
        stmt = stmt.where(TestCase.dataset_id.in_(dataset_ids))
    else:
        stmt = stmt.join(TestDataset, TestCase.dataset_id == TestDataset.id).where(
            TestDataset.project_id == project_id
        )
    rows = (await db.execute(stmt)).all()
    return {tid for tid, tags in rows if is_no_retrieval_expected(tags)}


async def compute_and_store_run_retrieval_summary(
    db: AsyncSession, run: EvalRun, project_id: UUID
) -> None:
    """Compute a finished run's URLs-path retrieval metrics and store them on ``run``.

    Best-effort: any failure is logged and swallowed so it never blocks run completion. The caller
    commits the run afterwards.
    """
    try:
        slice_rows = (
            await db.execute(
                select(TestCaseLabelingStatus.test_id, TestCaseLabelingStatus.slice).where(
                    TestCaseLabelingStatus.project_id == project_id,
                    TestCaseLabelingStatus.slice.is_not(None),
                )
            )
        ).all()
        slice_by_test = {tid: s for tid, s in slice_rows}
        results = (
            await db.execute(select(EvalResult).where(EvalResult.run_id == run.id))
        ).scalars().all()
        negatives = await negative_test_ids(db, project_id=project_id)
        summary = aggregate_run_retrieval_metrics(
            run, results, slice_by_test, exclude_test_ids=negatives
        ).model_dump(mode="json")

        # Overlay retrieval-path health derived from the target's per-result
        # diagnostics (result_metadata["retrieval_mode"]). A `keyword-fallback`
        # result means the target degraded to keyword-only retrieval (embeddings
        # throttled) — unrepresentative of prod. Surface the breakdown on the run
        # summary and warn so degraded runs can be flagged/excluded.
        mode_counts: dict[str, int] = {}
        for r in results:
            mode = (r.result_metadata or {}).get("retrieval_mode")
            if isinstance(mode, str) and mode:
                mode_counts[mode] = mode_counts.get(mode, 0) + 1
        if mode_counts:
            summary["retrieval_mode_counts"] = mode_counts
            degraded = mode_counts.get(DEGRADED_RETRIEVAL_MODE, 0)
            if degraded:
                logger.warning(
                    "Run %s: %d/%d results used keyword-only retrieval (target embeddings "
                    "throttled — degraded, not representative of prod); exclude from quality "
                    "comparison",
                    run.id,
                    degraded,
                    len(results),
                )

        run.retrieval_summary = summary
    except Exception as exc:  # noqa: BLE001
        logger.warning("Retrieval snapshot failed for run %s: %s", run.id, exc)


def _find_retrieval_details(graders: Any) -> dict[str, Any] | None:
    """First grader ``details`` dict that carries retrieval data (``retrieved_urls``)."""
    if not isinstance(graders, dict):
        return None
    for grader in graders.values():
        details = grader.get("details") if isinstance(grader, dict) else None
        if isinstance(details, dict) and "retrieved_urls" in details:
            return details
    return None


def _expected_from_details(details: dict[str, Any]) -> list[str]:
    """Reconstruct the ground-truth URL set the grader checked against.

    ``found_urls`` (expected URLs present in the response) + ``missing_urls`` (expected but
    absent) is exactly the case's expected set, split by presence.
    """
    found = details.get("found_urls") or []
    missing = details.get("missing_urls") or []
    out: list[str] = []
    for url in [*found, *missing]:
        if isinstance(url, str) and url not in out:
            out.append(url)
    return out


def _macro_avg_dict(dicts: list[dict[str, float]]) -> dict[str, float]:
    """Macro-average a list of {k: value} dicts key-wise."""
    if not dicts:
        return {}
    keys = {k for d in dicts for k in d}
    out: dict[str, float] = {}
    for k in keys:
        vals = [d[k] for d in dicts if k in d]
        out[k] = round(sum(vals) / len(vals), 4) if vals else 0.0
    return out


def _slice_summaries(cases: list[RetrievalCaseMetrics]) -> list[SliceMetrics]:
    """Macro-average recall/nDCG/bpref within each risk slice.

    Returns ``[]`` when no case carries an explicit slice (so the breakdown only appears once
    slices are actually used). Otherwise every case is grouped, with unassigned cases folding
    into the ``broad`` default so the breakdown covers the whole run.
    """
    if not any(c.slice for c in cases):
        return []
    grouped: dict[str, list[RetrievalCaseMetrics]] = {}
    for c in cases:
        grouped.setdefault(c.slice or DEFAULT_SLICE, []).append(c)

    out: list[SliceMetrics] = []
    for name, group in grouped.items():
        bprefs = [c.bpref for c in group if c.bpref is not None]
        out.append(
            SliceMetrics(
                slice=name,
                case_count=len(group),
                recall_at_k=_macro_avg_dict([c.recall_at_k for c in group]),
                ndcg_at_k=_macro_avg_dict([c.ndcg_at_k for c in group]),
                bpref=round(sum(bprefs) / len(bprefs), 4) if bprefs else None,
            )
        )
    # Stable, meaningful order: safety/adversarial first (where deep misses matter), then broad.
    order = {"safety": 0, "adversarial": 1, DEFAULT_SLICE: 2}
    out.sort(key=lambda s: (order.get(s.slice, 3), s.slice))
    return out


def _aggregate_rows(
    run_id: str | None,
    run_name: str | None,
    total_cases: int,
    rows: list[dict[str, Any]],
    ks: tuple[int, ...],
) -> RetrievalRunMetrics:
    """Shared core: turn per-case (expected, retrieved) rows into a run summary.

    Each row: ``{test_id, input, expected: list[str], retrieved: list[str], missing: list[str]}``.
    Rows with no expected ids are dropped (recall is undefined without ground truth). A row may
    also carry ``judged_nonrelevant: set[str]`` (chunk-label path); when present, the
    incomplete-judgment-safe metrics (bpref, condensed nDCG) are computed for that case and
    rolled up. The URL path omits it, so those metrics stay null there.
    """
    cases: list[RetrievalCaseMetrics] = []
    recalls: list[dict[str, float]] = []
    precisions: list[dict[str, float]] = []
    hit_rates: list[dict[str, float]] = []
    ndcgs: list[dict[str, float]] = []
    mrrs: list[float] = []
    bprefs: list[float] = []
    cndcgs: list[dict[str, float]] = []
    largest_k = str(max(ks))

    for row in rows:
        expected = row["expected"]
        retrieved = row["retrieved"]
        metrics = compute_retrieval_metrics(expected, retrieved, ks)
        if metrics is None:  # no ground truth → not measurable
            continue

        recall = metrics["recall_at_k"] or {}
        ndcg = metrics["ndcg_at_k"] or {}
        hit_rate = metrics["hit_rate_at_k"] or {}

        # Incomplete-judgment-safe metrics — only when the row carries a judged-non-relevant
        # set (the chunk-label path). bpref/condensed nDCG drop unjudged retrieved chunks
        # instead of scoring them as misses. When the row also carries graded ``gains`` (gold
        # grade per relevant chunk), nDCG and condensed nDCG score by grade rather than binary
        # presence, so a highly-relevant chunk up top beats a marginal one. The graded nDCG
        # replaces the binary ``ndcg`` before any roll-up so per-case and run-level agree.
        bpref: float | None = None
        cndcg: dict[str, float] = {}
        if "judged_nonrelevant" in row:
            nonrel = row["judged_nonrelevant"]
            # Empty gains (no graded labels) → fall back to binary scoring, not all-zero gains.
            gains = row.get("gains") or None
            bpref = compute_bpref(expected, nonrel, retrieved)
            cndcg = compute_condensed_ndcg_at_k(expected, nonrel, retrieved, ks, gains=gains) or {}
            if gains:
                ndcg = compute_graded_ndcg_at_k(gains, retrieved, ks) or ndcg

        recalls.append(recall)
        precisions.append(metrics["precision_at_k"] or {})
        hit_rates.append(hit_rate)
        ndcgs.append(ndcg)
        if metrics["mrr"] is not None:
            mrrs.append(metrics["mrr"])
        if bpref is not None:
            bprefs.append(bpref)
        if cndcg:
            cndcgs.append(cndcg)

        cases.append(
            RetrievalCaseMetrics(
                test_id=row["test_id"],
                dataset_id=row.get("dataset_id"),
                input=row.get("input"),
                expected_count=len(expected),
                retrieved_count=len(retrieved),
                relevant_count=metrics.get("relevant_count", 0),
                relevant_retrieved_at_k=metrics.get("relevant_retrieved_at_k") or {},
                relevant_retrieved_total=metrics.get("relevant_retrieved_total", 0),
                recall_at_k=recall,
                precision_at_k=metrics["precision_at_k"] or {},
                hit_rate_at_k=hit_rate,
                ndcg_at_k=ndcg,
                mrr=metrics["mrr"],
                first_relevant_rank=metrics["first_relevant_rank"],
                hit=hit_rate.get(largest_k, 0.0) >= 1.0,
                missing_urls=row.get("missing", []),
                bpref=round(bpref, 4) if bpref is not None else None,
                condensed_ndcg_at_k=cndcg,
                slice=row.get("slice"),
            )
        )

    if not cases:
        return RetrievalRunMetrics(
            available=False,
            run_id=run_id,
            run_name=run_name,
            total_cases=total_cases,
            evaluated_cases=0,
            ks=list(ks),
        )

    # Worst recall@largest_k first — surfaces the queries retrieval is failing.
    cases.sort(key=lambda c: c.recall_at_k.get(largest_k, 0.0))

    return RetrievalRunMetrics(
        available=True,
        run_id=run_id,
        run_name=run_name,
        total_cases=total_cases,
        evaluated_cases=len(cases),
        ks=list(ks),
        recall_at_k=_macro_avg_dict(recalls),
        precision_at_k=_macro_avg_dict(precisions),
        hit_rate_at_k=_macro_avg_dict(hit_rates),
        ndcg_at_k=_macro_avg_dict(ndcgs),
        mrr=round(sum(mrrs) / len(mrrs), 4) if mrrs else None,
        bpref=round(sum(bprefs) / len(bprefs), 4) if bprefs else None,
        condensed_ndcg_at_k=_macro_avg_dict(cndcgs),
        slices=_slice_summaries(cases),
        cases=cases,
    )


def aggregate_run_retrieval_metrics(
    run: EvalRun,
    results: Iterable[EvalResult],
    slice_by_test: dict[str, str] | None = None,
    ks: tuple[int, ...] = AGG_KS,
    exclude_test_ids: set[str] | None = None,
) -> RetrievalRunMetrics:
    """Run summary from the ``contains_urls`` grader's per-case URL captures.

    ``exclude_test_ids`` (normalized TestCase test_ids) drops negative cases before
    aggregation, even if stale ground-truth URLs are still attached to their results.
    """
    slice_by_test = slice_by_test or {}
    excluded = 0
    result_list = []
    for r in results:
        if exclude_test_ids and normalize_result_test_id(r.test_id) in exclude_test_ids:
            excluded += 1
            continue
        result_list.append(r)
    rows: list[dict[str, Any]] = []
    for r in result_list:
        details = _find_retrieval_details(r.graders)
        if details is None:
            continue
        rows.append(
            {
                "test_id": r.test_id,
                "input": (r.input or None) and str(r.input)[:200],
                "expected": _expected_from_details(details),
                "retrieved": [u for u in (details.get("retrieved_urls") or []) if isinstance(u, str)],
                "missing": [u for u in (details.get("missing_urls") or []) if isinstance(u, str)],
                "slice": slice_by_test.get(r.test_id),
            }
        )
    summary = _aggregate_rows(str(run.id), run.name, len(result_list), rows, ks)
    summary.negative_cases_excluded = excluded
    return summary


def aggregate_retrieval_metrics_from_labels(
    cases: Iterable[tuple[str, str | None]],
    retrieved_by_test: dict[str, list[str]],
    relevant_by_test: dict[str, set[str]],
    judged_nonrelevant_by_test: dict[str, set[str]] | None = None,
    slice_by_test: dict[str, str] | None = None,
    grade_by_test: dict[str, dict[str, int]] | None = None,
    *,
    dataset_id: str | None = None,
    dataset_name: str | None = None,
    dataset_by_test: dict[str, str] | None = None,
    ks: tuple[int, ...] = AGG_KS,
) -> RetrievalRunMetrics:
    """Summary from human chunk labels vs. a live retrieval probe, over a dataset's cases.

    ``cases`` are ``(test_id, query)`` pairs from the dataset. ``retrieved_by_test`` maps
    test_id → the ranked chunk ids the live retrieval probe returned for that query (what "the
    system" retrieves now). ``relevant_by_test`` maps test_id → chunk ids judged relevant
    (pooled across all labelers). ``judged_nonrelevant_by_test`` enables the
    incomplete-judgment-safe metrics (bpref, condensed nDCG); ``grade_by_test`` makes nDCG use
    graded gains; ``slice_by_test`` drives the per-slice breakdown. Cases without any relevant
    label are dropped (recall is undefined without ground truth).
    """
    judged_nonrelevant_by_test = judged_nonrelevant_by_test or {}
    grade_by_test = grade_by_test or {}
    slice_by_test = slice_by_test or {}
    dataset_by_test = dataset_by_test or {}
    case_list = list(cases)
    rows: list[dict[str, Any]] = []
    for test_id, query in case_list:
        relevant = relevant_by_test.get(test_id)
        if not relevant:
            continue
        rows.append(
            {
                "test_id": test_id,
                "dataset_id": dataset_by_test.get(test_id),
                "input": (query or None) and str(query)[:200],
                "expected": list(relevant),
                "retrieved": retrieved_by_test.get(test_id, []),
                "missing": [],
                "judged_nonrelevant": judged_nonrelevant_by_test.get(test_id, set()),
                "gains": {k: float(v) for k, v in grade_by_test.get(test_id, {}).items()},
                "slice": slice_by_test.get(test_id),
            }
        )
    return _aggregate_rows(dataset_id, dataset_name, len(case_list), rows, ks)
