"""Tests for run-level retrieval-metrics aggregation
(services/retrieval_metrics_aggregate.py)."""

from __future__ import annotations

from uuid import uuid4

from app.models.evaluations import EvalResult, EvalRun
from app.services.retrieval_metrics_aggregate import aggregate_run_retrieval_metrics


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
