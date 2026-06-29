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

from typing import Any, Iterable

from app.models.chunk_labels import DEFAULT_SLICE
from app.models.evaluations import EvalResult, EvalRun
from app.schemas.retrieval import RetrievalCaseMetrics, RetrievalRunMetrics, SliceMetrics
from app.services.chunk_labeling import retrieved_chunk_ids
from app.services.retrieval_metrics import (
    compute_bpref,
    compute_condensed_ndcg_at_k,
    compute_graded_ndcg_at_k,
    compute_retrieval_metrics,
)

# Richer k grid than the grader default so the run view can draw a recall curve.
AGG_KS: tuple[int, ...] = (1, 3, 5, 10)


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
    run: EvalRun,
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
                input=row.get("input"),
                expected_count=len(expected),
                retrieved_count=len(retrieved),
                recall_at_k=recall,
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
            run_id=str(run.id),
            run_name=run.name,
            total_cases=total_cases,
            evaluated_cases=0,
            ks=list(ks),
        )

    # Worst recall@largest_k first — surfaces the queries retrieval is failing.
    cases.sort(key=lambda c: c.recall_at_k.get(largest_k, 0.0))

    return RetrievalRunMetrics(
        available=True,
        run_id=str(run.id),
        run_name=run.name,
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
) -> RetrievalRunMetrics:
    """Run summary from the ``contains_urls`` grader's per-case URL captures."""
    slice_by_test = slice_by_test or {}
    result_list = list(results)
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
    return _aggregate_rows(run, len(result_list), rows, ks)


def aggregate_run_retrieval_metrics_from_labels(
    run: EvalRun,
    results: Iterable[EvalResult],
    relevant_by_test: dict[str, set[str]],
    judged_nonrelevant_by_test: dict[str, set[str]] | None = None,
    slice_by_test: dict[str, str] | None = None,
    grade_by_test: dict[str, dict[str, int]] | None = None,
    ks: tuple[int, ...] = AGG_KS,
) -> RetrievalRunMetrics:
    """Run summary from human chunk labels, with pooled recall.

    ``relevant_by_test`` maps test_id → the set of chunk ids judged relevant for that
    query (pooled across all runs). ``judged_nonrelevant_by_test`` maps test_id → chunk ids
    explicitly judged *not* relevant; supplying it enables the incomplete-judgment-safe
    metrics (bpref, condensed nDCG), which need to tell judged-irrelevant chunks apart from
    merely-unjudged ones. ``grade_by_test`` maps test_id → ``{chunk_id: gold grade}`` for the
    relevant chunks; supplying it makes nDCG / condensed nDCG use graded gains (gain = grade)
    instead of binary relevance. ``slice_by_test`` maps test_id → its risk slice for the
    per-slice breakdown. Retrieved chunk ids come from each result's captured
    ``retrieved_chunks`` in rank order.
    """
    judged_nonrelevant_by_test = judged_nonrelevant_by_test or {}
    grade_by_test = grade_by_test or {}
    slice_by_test = slice_by_test or {}
    result_list = list(results)
    rows: list[dict[str, Any]] = []
    for r in result_list:
        relevant = relevant_by_test.get(r.test_id)
        if not relevant:
            continue
        rows.append(
            {
                "test_id": r.test_id,
                "input": (r.input or None) and str(r.input)[:200],
                "expected": list(relevant),
                "retrieved": retrieved_chunk_ids(r),
                "missing": [],
                "judged_nonrelevant": judged_nonrelevant_by_test.get(r.test_id, set()),
                "gains": {k: float(v) for k, v in grade_by_test.get(r.test_id, {}).items()},
                "slice": slice_by_test.get(r.test_id),
            }
        )
    return _aggregate_rows(run, len(result_list), rows, ks)
