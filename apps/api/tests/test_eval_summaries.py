"""Tests for run-level summary aggregation, incl. retrieval-metric macro-averages."""

from __future__ import annotations

from app.routers.eval_helpers import _compute_summaries


def _result(
    recall: dict | None,
    *,
    precision: dict | None = None,
    hit_rate: dict | None = None,
    passed: bool = True,
) -> dict:
    grader = {"pass": passed, "skipped": False}
    details = {}
    if recall is not None:
        details["recall_at_k"] = recall
    if precision is not None:
        details["precision_at_k"] = precision
    if hit_rate is not None:
        details["hit_rate_at_k"] = hit_rate
    if details:
        grader["details"] = details
    return {"graders": {"sourceRetrieval": grader}, "scores": {}}


def test_recall_summary_is_macro_averaged_across_results():
    results = [
        _result({"5": 1.0, "10": 1.0}),
        _result({"5": 0.5, "10": 1.0}),
        _result({"5": 0.0, "10": 0.0}),
    ]
    grader_summary, _ = _compute_summaries(results)
    rs = grader_summary["sourceRetrieval"]["recall_summary"]
    assert rs["count"] == 3
    assert rs["recall_at_k"]["5"] == 0.5  # (1.0 + 0.5 + 0.0) / 3
    assert rs["recall_at_k"]["10"] == (1.0 + 1.0 + 0.0) / 3


def test_recall_summary_absent_when_no_recall_details():
    grader_summary, _ = _compute_summaries([_result(None)])
    assert "recall_summary" not in grader_summary["sourceRetrieval"]


def test_recall_summary_only_averages_results_that_have_it():
    # A run where some cases skipped the URL check (no recall) and some ran it.
    results = [_result(None), _result({"5": 1.0, "10": 1.0}), _result({"5": 0.0, "10": 0.5})]
    rs = _compute_summaries(results)[0]["sourceRetrieval"]["recall_summary"]
    assert rs["count"] == 2
    assert rs["recall_at_k"]["5"] == 0.5
    assert rs["recall_at_k"]["10"] == 0.75


def test_precision_and_hit_rate_summaries_macro_averaged():
    results = [
        _result({"5": 1.0, "10": 1.0}, precision={"5": 0.2, "10": 0.1}, hit_rate={"5": 1.0, "10": 1.0}),
        _result({"5": 0.0, "10": 0.5}, precision={"5": 0.0, "10": 0.1}, hit_rate={"5": 0.0, "10": 1.0}),
    ]
    summary = _compute_summaries(results)[0]["sourceRetrieval"]
    ps = summary["precision_summary"]
    assert ps["count"] == 2
    assert ps["precision_at_k"]["5"] == 0.1  # (0.2 + 0.0) / 2
    assert ps["precision_at_k"]["10"] == 0.1
    hs = summary["hit_rate_summary"]
    assert hs["count"] == 2
    assert hs["hit_rate_at_k"]["5"] == 0.5  # (1.0 + 0.0) / 2 -> share of queries that hit
    assert hs["hit_rate_at_k"]["10"] == 1.0


def test_precision_and_hit_rate_summaries_absent_when_no_details():
    summary = _compute_summaries([_result(None)])[0]["sourceRetrieval"]
    assert "precision_summary" not in summary
    assert "hit_rate_summary" not in summary
