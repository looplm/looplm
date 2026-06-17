"""Tests for run-level summary aggregation, incl. recall@k macro-average."""

from __future__ import annotations

from app.routers.eval_helpers import _compute_summaries


def _result(recall: dict | None, *, passed: bool = True) -> dict:
    grader = {"pass": passed, "skipped": False}
    if recall is not None:
        grader["details"] = {"recall_at_k": recall}
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
