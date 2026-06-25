"""Tests for run-level retrieval-metrics aggregation
(services/retrieval_metrics_aggregate.py)."""

from __future__ import annotations

from uuid import uuid4

from app.models.evaluations import EvalResult, EvalRun
from app.services.retrieval_metrics_aggregate import (
    aggregate_run_retrieval_metrics,
    aggregate_run_retrieval_metrics_from_labels,
)


def _run():
    return EvalRun(id=uuid4(), name="nightly-rag")


def _result(*, test_id, found, missing, retrieved, input_text="q"):
    return EvalResult(
        id=uuid4(),
        run_id=uuid4(),
        test_id=test_id,
        pass_=True,
        input=input_text,
        graders={
            "contains_urls": {
                "pass": not missing,
                "details": {
                    "found_urls": found,
                    "missing_urls": missing,
                    "retrieved_urls": retrieved,
                },
            }
        },
    )


HIT = "https://x.example/relevant"
MISS = "https://x.example/irrelevant"


def test_unavailable_without_ground_truth():
    # A result whose grader has no retrieval details at all.
    r = EvalResult(id=uuid4(), run_id=uuid4(), test_id="t1", pass_=True, graders={})
    out = aggregate_run_retrieval_metrics(_run(), [r])
    assert out.available is False
    assert out.evaluated_cases == 0
    assert out.total_cases == 1


def test_perfect_retrieval():
    results = [
        _result(test_id="t1", found=[HIT], missing=[], retrieved=[HIT, MISS]),
        _result(test_id="t2", found=[HIT], missing=[], retrieved=[HIT]),
    ]
    out = aggregate_run_retrieval_metrics(_run(), results)
    assert out.available is True
    assert out.evaluated_cases == 2
    assert out.recall_at_k["10"] == 1.0
    assert out.mrr == 1.0
    assert out.ndcg_at_k["10"] == 1.0
    assert all(c.hit for c in out.cases)


def test_macro_average_and_worst_first_ordering():
    results = [
        # Full recall.
        _result(test_id="good", found=[HIT], missing=[], retrieved=[HIT]),
        # Relevant doc never retrieved → recall 0, miss recorded.
        _result(test_id="bad", found=[], missing=[HIT], retrieved=[MISS]),
    ]
    out = aggregate_run_retrieval_metrics(_run(), results)
    assert out.evaluated_cases == 2
    # Macro recall@10 = mean(1.0, 0.0) = 0.5
    assert out.recall_at_k["10"] == 0.5
    # Worst recall first.
    assert out.cases[0].test_id == "bad"
    assert out.cases[0].hit is False
    assert out.cases[0].missing_urls == [HIT]
    assert out.cases[0].first_relevant_rank is None
    assert out.cases[-1].test_id == "good"


def test_rank_sensitivity_in_mrr():
    # Relevant doc buried at rank 3 → MRR 1/3.
    results = [_result(test_id="t", found=[HIT], missing=[], retrieved=[MISS, MISS + "2", HIT])]
    out = aggregate_run_retrieval_metrics(_run(), results)
    assert out.mrr == round(1.0 / 3, 4)
    assert out.cases[0].first_relevant_rank == 3


# --- chunk-label path with incomplete-judgment-safe metrics ---

def _chunk_result(test_id, chunk_ids):
    """An EvalResult whose captured retrieved_chunks are the given ids in rank order."""
    return EvalResult(
        id=uuid4(),
        run_id=uuid4(),
        test_id=test_id,
        pass_=True,
        input="q",
        result_metadata={"retrieved_chunks": [{"chunk_id": c} for c in chunk_ids]},
    )


def test_labels_path_reports_bpref_and_condensed_ndcg():
    # Pool for t1: r1 relevant, n1 judged-non-relevant, u1 unjudged. Retrieved [u1, r1, n1].
    results = [_chunk_result("t1", ["u1", "r1", "n1"])]
    out = aggregate_run_retrieval_metrics_from_labels(
        _run(),
        results,
        relevant_by_test={"t1": {"r1"}},
        judged_nonrelevant_by_test={"t1": {"n1"}},
    )
    assert out.available is True
    # r1 ranked above n1, unjudged u1 ignored → perfect bpref + condensed nDCG.
    assert out.bpref == 1.0
    assert out.condensed_ndcg_at_k["10"] == 1.0
    assert out.cases[0].bpref == 1.0


def test_labels_path_without_nonrelevant_still_works():
    # No judged-non-relevant set supplied → bpref reduces to relevant-fraction, no crash.
    results = [_chunk_result("t1", ["r1"])]
    out = aggregate_run_retrieval_metrics_from_labels(
        _run(), results, relevant_by_test={"t1": {"r1", "r2"}}
    )
    assert out.bpref == 0.5  # only 1 of 2 relevant retrieved
    assert out.recall_at_k["10"] == 0.5
