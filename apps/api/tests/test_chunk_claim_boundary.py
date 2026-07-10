"""Unit tests for claim-boundary analysis (fake LLM, pure adjacency/aggregation)."""

import json

import pytest

from app.services.analysis_llm import LlmUsageInfo
from app.services.chunk_judge_common import AiJudgeChunk
from app.services.chunk_claim_boundary import (
    analyze_claim_boundary,
    decompose_claims,
    ground_claims,
    has_adjacent_pair,
)


def _usage():
    return LlmUsageInfo(
        input_tokens=10, output_tokens=10, total_tokens=20,
        cost_usd=None, cached_tokens=0, reasoning_tokens=0, duration_ms=1,
    )


class FakeLlm:
    def __init__(self, responses):
        self._responses = list(responses)

    async def tracked_chat_completion(self, messages, *, temperature=0.2, response_format=None):
        return self._responses.pop(0), _usage()


# ── Decompose ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_decompose_claims_parses_and_trims():
    llm = FakeLlm([json.dumps({"claims": ["The dose is 5 mg.", "  ", 42, "It is taken daily."]})])
    claims, usage = await decompose_claims(llm, "The dose is 5 mg, taken daily.")
    assert claims == ["The dose is 5 mg.", "It is taken daily."]
    assert usage.total_tokens == 20


# ── Ground ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ground_claims_assigns_statuses():
    chunks = [AiJudgeChunk("x", "chunk one"), AiJudgeChunk("y", "chunk two")]
    llm = FakeLlm([json.dumps({"groundings": [
        {"claim": 1, "chunks": [1]},
        {"claim": 2, "chunks": [1, 2]},
        {"claim": 3, "chunks": []},
    ]})])
    groundings, _ = await ground_claims(llm, ["a", "b", "c"], chunks)
    assert [g.status for g in groundings] == ["single", "cross_boundary", "unsupported"]
    assert groundings[1].chunk_ids == ["x", "y"]


@pytest.mark.asyncio
async def test_ground_claims_missing_entries_are_unsupported():
    chunks = [AiJudgeChunk("x", "chunk one")]
    llm = FakeLlm([json.dumps({"groundings": [{"claim": 99, "chunks": [1]}]})])
    groundings, _ = await ground_claims(llm, ["only claim"], chunks)
    assert groundings[0].status == "unsupported"


# ── Adjacency ────────────────────────────────────────────────────────────────

def test_adjacent_pair_same_parent_consecutive_ordinals():
    docs = {
        "x": {"page_id": "p1", "chunk_index": 3},
        "y": {"page_id": "p1", "chunk_index": 4},
        "z": {"page_id": "p2", "chunk_index": 4},
    }
    assert has_adjacent_pair(["x", "y"], docs, parent_field="page_id", ordinal_field="chunk_index")
    assert not has_adjacent_pair(["x", "z"], docs, parent_field="page_id", ordinal_field="chunk_index")
    assert not has_adjacent_pair(["x", "y"], docs, parent_field=None, ordinal_field="chunk_index")


# ── Aggregation ──────────────────────────────────────────────────────────────

def _row(status, adjacent=False, case="t1"):
    return {
        "test_case_id": case, "claim": "c", "chunk_ids": ["a", "b"],
        "status": status, "adjacent": adjacent,
    }


def test_analyze_claim_boundary_thresholds_and_examples():
    rows = (
        [_row("single")] * 5
        + [_row("cross_boundary", adjacent=True), _row("cross_boundary")]
        + [_row("unsupported")]
    )
    metrics, findings = analyze_claim_boundary(
        rows, dataset_id="ds", cases_analyzed=3, cases_skipped=1
    )
    assert metrics["claims_total"] == 8
    assert metrics["single_chunk"] == 5
    assert metrics["cross_boundary"] == 2
    assert metrics["cross_adjacent"] == 1
    assert metrics["unsupported"] == 1
    assert metrics["cross_boundary_pct"] == 25.0
    assert len(metrics["examples"]) == 2
    assert findings and findings[0].family == "claim_boundary"


def test_analyze_claim_boundary_quiet_below_threshold():
    rows = [_row("single")] * 9 + [_row("cross_boundary")]
    _, findings = analyze_claim_boundary(rows, dataset_id=None, cases_analyzed=5, cases_skipped=0)
    assert findings == []
