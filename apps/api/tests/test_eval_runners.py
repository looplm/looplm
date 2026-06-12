"""Tests for eval runner helpers — retrieved-URL extraction and the contains_urls grader."""

from __future__ import annotations

import json

import pytest

from app.models.models import Evaluator, EvaluatorType, TestCase
from app.services.eval_executor_helpers import _run_evaluators_for_turn
from app.services.eval_runners import _run_deterministic
from app.services.retrieval_config import extract_retrieved_urls


# --- extract_retrieved_urls ---

def test_retrieved_urls_from_top_level_sources():
    raw = json.dumps({
        "answer": "hi",
        "sources": [
            {"url": "https://a.example/page"},
            {"url": "https://b.example/doc", "title": "B"},
            {"url": "https://a.example/page"},  # duplicate
        ],
    })
    assert extract_retrieved_urls(raw) == ["https://a.example/page", "https://b.example/doc"]


def test_retrieved_urls_from_sources_under_payload_key():
    raw = json.dumps({
        "answer": "hi",
        "myContext": {"sources": [{"url": "https://a.example/x"}]},
    })
    assert extract_retrieved_urls(raw, payload_key="myContext") == ["https://a.example/x"]


def test_retrieved_urls_from_sources_under_fallback_key():
    raw = json.dumps({
        "retrievedContext": {"sources": [{"url": "https://a.example/x"}]},
    })
    assert extract_retrieved_urls(raw) == ["https://a.example/x"]


def test_retrieved_urls_regex_fallback_over_retrieval_context():
    raw = json.dumps({
        "answer": "see https://unrelated.example/in-answer",
        "retrievalContext": "Chunk from https://a.example/p1. More at https://b.example/p2, done.",
    })
    # Regex runs over the retrieval context only, not the answer
    assert extract_retrieved_urls(raw) == ["https://a.example/p1", "https://b.example/p2"]


def test_retrieved_urls_regex_fallback_over_raw_response():
    raw = json.dumps({"answer": "cited: https://a.example/p1 and (https://b.example/p2)."})
    assert extract_retrieved_urls(raw) == ["https://a.example/p1", "https://b.example/p2"]


def test_retrieved_urls_non_json_input_uses_regex():
    assert extract_retrieved_urls("plain text https://a.example/x end") == ["https://a.example/x"]


def test_retrieved_urls_normalizes_confluence_slugs():
    raw = "https://co.example/wiki/spaces/AB/pages/123/Some%20Mangled+Slug"
    assert extract_retrieved_urls(raw) == ["https://co.example/wiki/spaces/AB/pages/123"]


def test_retrieved_urls_empty_and_capped():
    assert extract_retrieved_urls("") == []
    assert extract_retrieved_urls("no urls here") == []
    many = " ".join(f"https://e.example/{i}" for i in range(50))
    assert len(extract_retrieved_urls(many, limit=30)) == 30


# --- contains_urls grader ---

def _contains_urls_evaluator() -> Evaluator:
    return Evaluator(
        name="sourceRetrieval",
        type=EvaluatorType.deterministic,
        config={"check_type": "contains_urls"},
        affects_pass=True,
    )


def test_contains_urls_includes_retrieved_urls_in_details():
    tc = TestCase(expected_page_urls=["https://a.example/p1", "https://b.example/p2"])
    raw = json.dumps({
        "answer": "x",
        "sources": [{"url": "https://a.example/p1"}, {"url": "https://c.example/other"}],
    })
    result = _run_deterministic(_contains_urls_evaluator(), "x", tc, context=raw)
    assert result["pass"] is False
    assert result["details"]["found_urls"] == ["https://a.example/p1"]
    assert result["details"]["missing_urls"] == ["https://b.example/p2"]
    assert result["details"]["retrieved_urls"] == [
        "https://a.example/p1",
        "https://c.example/other",
    ]


@pytest.mark.asyncio
async def test_run_evaluators_for_turn_preserves_details():
    tc = TestCase(expected_page_urls=["https://a.example/p1"])
    raw = json.dumps({"sources": [{"url": "https://c.example/other"}]})
    graders, overall_pass, _scores, _usages = await _run_evaluators_for_turn(
        [_contains_urls_evaluator()], None, "q", "answer", None, raw, tc,
    )
    assert overall_pass is False
    g = graders["sourceRetrieval"]
    assert g.details is not None
    assert g.details["missing_urls"] == ["https://a.example/p1"]
    assert g.details["retrieved_urls"] == ["https://c.example/other"]
