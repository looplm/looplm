"""Tests for the failure_pattern classifier service and classify-failures endpoint."""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

from app.models.models import Evaluator, EvaluatorType
from app.services.failure_pattern import (
    NEEDS_MORE_INFO,
    UNKNOWN,
    aggregate_root_causes,
    aggregate_run_patterns,
    classify_assistant_intent,
    compute_failure_pattern,
    compute_root_cause,
    derive_grader_pattern,
)


# ---------------------------------------------------------------------------
# derive_grader_pattern — pure function, no async
# ---------------------------------------------------------------------------

def test_derive_grader_pattern_empty():
    assert derive_grader_pattern({}, {}) == []
    assert derive_grader_pattern(None, {}) == []


def test_derive_grader_pattern_picks_affects_pass_failures():
    graders = {
        "faithfulness": {"pass": False, "skipped": False},
        "helpfulness": {"pass": False, "skipped": False},
        "source_retrieval": {"pass": False, "skipped": False},
    }
    affects_pass = {"faithfulness": True, "helpfulness": False, "source_retrieval": True}
    assert derive_grader_pattern(graders, affects_pass) == ["faithfulness", "source_retrieval"]


def test_derive_grader_pattern_ignores_skipped_and_passed():
    graders = {
        "faithfulness": {"pass": False, "skipped": True},
        "source_retrieval": {"pass": True, "skipped": False},
        "image_missing": {"pass": False, "skipped": False},
    }
    affects_pass = {"faithfulness": True, "source_retrieval": True, "image_missing": True}
    assert derive_grader_pattern(graders, affects_pass) == ["image_missing"]


def test_derive_grader_pattern_sorted():
    graders = {
        "zeta": {"pass": False, "skipped": False},
        "alpha": {"pass": False, "skipped": False},
    }
    affects_pass = {"zeta": True, "alpha": True}
    assert derive_grader_pattern(graders, affects_pass) == ["alpha", "zeta"]


# ---------------------------------------------------------------------------
# compute_failure_pattern — async, with stub LLM
# ---------------------------------------------------------------------------

class _StubLlm:
    """Minimal stand-in for AnalysisLlmService used by compute_failure_pattern."""

    def __init__(self, intent: str) -> None:
        self._intent = intent
        self.calls: int = 0

    async def tracked_chat_completion(self, *args: Any, **kwargs: Any):
        self.calls += 1
        return json.dumps({"intent": self._intent}), None


@pytest.mark.asyncio
async def test_compute_failure_pattern_passed_test_returns_empty():
    patch, usage = await compute_failure_pattern(
        pass_=True,
        graders={"faithfulness": {"pass": True, "skipped": False}},
        output="An answer.",
        affects_pass_map={"faithfulness": True},
        llm=None,
    )
    assert patch == {}
    assert usage is None


@pytest.mark.asyncio
async def test_compute_failure_pattern_grader_only_no_llm():
    patch, _ = await compute_failure_pattern(
        pass_=False,
        graders={"faithfulness": {"pass": False, "skipped": False}},
        output="Some answer.",
        affects_pass_map={"faithfulness": True},
        llm=None,
    )
    assert patch["failure_pattern"] == "faithfulness"
    assert patch["grader_pattern"] == ["faithfulness"]
    assert "assistant_intent" not in patch


@pytest.mark.asyncio
async def test_compute_failure_pattern_clarifying_question_overrides_grader():
    llm = _StubLlm(intent="clarifying_question")
    patch, _ = await compute_failure_pattern(
        pass_=False,
        graders={"faithfulness": {"pass": False, "skipped": False}},
        output="Could you tell me which date range you mean?",
        affects_pass_map={"faithfulness": True},
        llm=llm,
    )
    assert patch["failure_pattern"] == NEEDS_MORE_INFO
    assert patch["grader_pattern"] == ["faithfulness"]
    assert patch["assistant_intent"] == "clarifying_question"
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_compute_failure_pattern_answer_intent_uses_grader_pattern():
    llm = _StubLlm(intent="answer")
    patch, _ = await compute_failure_pattern(
        pass_=False,
        graders={"faithfulness": {"pass": False, "skipped": False}},
        output="42",
        affects_pass_map={"faithfulness": True},
        llm=llm,
    )
    assert patch["failure_pattern"] == "faithfulness"
    assert "assistant_intent" not in patch


@pytest.mark.asyncio
async def test_compute_failure_pattern_refusal_intent_recorded_but_no_override():
    llm = _StubLlm(intent="refusal")
    patch, _ = await compute_failure_pattern(
        pass_=False,
        graders={"faithfulness": {"pass": False, "skipped": False}},
        output="I cannot help with that.",
        affects_pass_map={"faithfulness": True},
        llm=llm,
    )
    assert patch["failure_pattern"] == "faithfulness"
    assert patch["assistant_intent"] == "refusal"


@pytest.mark.asyncio
async def test_compute_failure_pattern_falls_back_to_unknown_when_no_affects_pass_failures():
    patch, _ = await compute_failure_pattern(
        pass_=False,
        graders={"helpfulness": {"pass": False, "skipped": False}},
        output="answer",
        affects_pass_map={"helpfulness": False},
        llm=None,
    )
    assert patch["failure_pattern"] == UNKNOWN
    assert patch["grader_pattern"] == []


@pytest.mark.asyncio
async def test_classify_assistant_intent_invalid_json_returns_answer():
    class _BadJsonLlm:
        async def tracked_chat_completion(self, *args, **kwargs):
            return "not-json", None

    intent, _ = await classify_assistant_intent("anything", _BadJsonLlm())
    assert intent == "answer"


@pytest.mark.asyncio
async def test_classify_assistant_intent_empty_output_skips_llm():
    class _RecordingLlm:
        calls = 0
        async def tracked_chat_completion(self, *args, **kwargs):
            type(self).calls += 1
            return json.dumps({"intent": "answer"}), None

    rec = _RecordingLlm()
    intent, _ = await classify_assistant_intent("   ", rec)
    assert intent == "answer"
    assert type(rec).calls == 0


# ---------------------------------------------------------------------------
# aggregate_run_patterns
# ---------------------------------------------------------------------------

def test_aggregate_run_patterns_counts_and_ignores_none():
    assert aggregate_run_patterns(
        ["faithfulness", "faithfulness", "needs_more_info", None]
    ) == {"faithfulness": 2, "needs_more_info": 1}


def test_aggregate_run_patterns_empty():
    assert aggregate_run_patterns([]) == {}


# ---------------------------------------------------------------------------
# compute_root_cause — retrieval vs generation attribution
# ---------------------------------------------------------------------------

class _SufficiencyLlm:
    """Stub returning a fixed context-sufficiency verdict; counts calls."""

    def __init__(self, sufficiency: str, missing: list[str] | None = None) -> None:
        self._payload = {"sufficiency": sufficiency, "missing_facts": missing or []}
        self.calls = 0

    async def tracked_chat_completion(self, *args: Any, **kwargs: Any):
        self.calls += 1
        return json.dumps(self._payload), None


@pytest.mark.asyncio
async def test_root_cause_passed_test_returns_empty():
    patch, usage = await compute_root_cause(
        pass_=True, grader_pattern=[], affects_pass_map={},
        question="q", output="a", expected="e",
        retrieval_context="ctx", llm=None,
    )
    assert patch == {} and usage is None


@pytest.mark.asyncio
async def test_root_cause_gate_no_retrieval_is_indeterminate():
    llm = _SufficiencyLlm("insufficient")
    patch, usage = await compute_root_cause(
        pass_=False, grader_pattern=["faithfulness"],
        affects_pass_map={"faithfulness": True},
        question="q", output="a", expected="e",
        retrieval_context="", llm=llm,
    )
    assert patch["root_cause"]["category"] == "indeterminate"
    assert patch["root_cause"]["source"] == "deterministic"
    assert llm.calls == 0  # gated before any LLM call
    assert usage is None


@pytest.mark.asyncio
async def test_root_cause_deterministic_retrieval_from_grader():
    """A failing retrieval grader → retrieval, no LLM needed. camelCase name."""
    llm = _SufficiencyLlm("sufficient")
    patch, _ = await compute_root_cause(
        pass_=False, grader_pattern=["sourceRetrieval"],
        affects_pass_map={"sourceRetrieval": True, "faithfulness": True},
        question="q", output="a", expected="e",
        retrieval_context="some context", llm=llm,
    )
    assert patch["root_cause"]["category"] == "retrieval"
    assert patch["root_cause"]["confidence"] == "high"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_root_cause_deterministic_retrieval_snake_case():
    """snake_case grader names normalise to the same signal."""
    patch, _ = await compute_root_cause(
        pass_=False, grader_pattern=["source_retrieval"],
        affects_pass_map={"source_retrieval": True},
        question="q", output="a", expected="e",
        retrieval_context="some context", llm=None,
    )
    assert patch["root_cause"]["category"] == "retrieval"


@pytest.mark.asyncio
async def test_root_cause_deterministic_generation_when_retrieval_grader_passed():
    """Grounding grader failed while a configured retrieval grader passed → generation."""
    llm = _SufficiencyLlm("sufficient")
    patch, _ = await compute_root_cause(
        pass_=False, grader_pattern=["faithfulness"],
        affects_pass_map={"sourceRetrieval": True, "faithfulness": True},
        question="q", output="a", expected="e",
        retrieval_context="some context", llm=llm,
    )
    assert patch["root_cause"]["category"] == "generation"
    assert patch["root_cause"]["confidence"] == "high"
    assert llm.calls == 0  # resolved deterministically


@pytest.mark.asyncio
async def test_root_cause_llm_insufficient_context_is_retrieval():
    """No retrieval grader configured → ambiguous → judge says insufficient → retrieval."""
    llm = _SufficiencyLlm("insufficient", missing=["the launch date"])
    patch, usage = await compute_root_cause(
        pass_=False, grader_pattern=["faithfulness"],
        affects_pass_map={"faithfulness": True},
        question="q", output="a", expected="e",
        retrieval_context="some context", llm=llm,
    )
    assert patch["root_cause"]["category"] == "retrieval"
    assert patch["root_cause"]["source"] == "llm"
    assert patch["root_cause"]["missing_facts"] == ["the launch date"]
    assert llm.calls == 1
    assert usage is None  # stub returns None usage


@pytest.mark.asyncio
async def test_root_cause_llm_sufficient_context_with_grounding_failure_is_generation():
    llm = _SufficiencyLlm("sufficient")
    patch, _ = await compute_root_cause(
        pass_=False, grader_pattern=["faithfulness"],
        affects_pass_map={"faithfulness": True},
        question="q", output="a", expected="e",
        retrieval_context="some context", llm=llm,
    )
    assert patch["root_cause"]["category"] == "generation"
    assert patch["root_cause"]["source"] == "llm"


@pytest.mark.asyncio
async def test_root_cause_llm_sufficient_context_no_grounding_failure_is_task_spec():
    llm = _SufficiencyLlm("sufficient")
    patch, _ = await compute_root_cause(
        pass_=False, grader_pattern=["answerRelevance"],
        affects_pass_map={"answerRelevance": True},
        question="q", output="a", expected="e",
        retrieval_context="some context", llm=llm,
    )
    assert patch["root_cause"]["category"] == "task_spec"


@pytest.mark.asyncio
async def test_root_cause_ambiguous_without_llm_is_low_confidence_indeterminate():
    patch, usage = await compute_root_cause(
        pass_=False, grader_pattern=["answerRelevance"],
        affects_pass_map={"answerRelevance": True},
        question="q", output="a", expected="e",
        retrieval_context="some context", llm=None,
    )
    assert patch["root_cause"]["category"] == "indeterminate"
    assert patch["root_cause"]["confidence"] == "low"
    assert usage is None


def test_aggregate_root_causes_counts_and_ignores_none():
    assert aggregate_root_causes(
        ["retrieval", "retrieval", "generation", None]
    ) == {"retrieval": 2, "generation": 1}


def test_aggregate_root_causes_empty():
    assert aggregate_root_causes([]) == {}


# ---------------------------------------------------------------------------
# classify-failures endpoint — integration test against the in-memory app
# ---------------------------------------------------------------------------

async def _seed_run_with_failures(client, auth_headers, db_session, test_project):
    """Import a run with two failing results (different grader pattern) + one pass."""
    db_session.add(Evaluator(
        id=uuid4(),
        project_id=test_project.id,
        name="faithfulness",
        display_name="Faithfulness",
        type=EvaluatorType.llm_judge,
        affects_pass=True,
        relevance="core",
    ))
    db_session.add(Evaluator(
        id=uuid4(),
        project_id=test_project.id,
        name="source_retrieval",
        display_name="Source Retrieval",
        type=EvaluatorType.llm_judge,
        affects_pass=True,
        relevance="core",
    ))
    await db_session.commit()

    resp = await client.post(
        "/api/evals/import",
        headers=auth_headers,
        json={
            "name": "Pattern Test Run",
            "results": [
                {
                    "test_id": "fail-faith",
                    "pass": False,
                    "output": "Something",
                    "graders": {
                        "faithfulness": {"pass": False},
                        "source_retrieval": {"pass": True},
                    },
                },
                {
                    "test_id": "fail-source",
                    "pass": False,
                    "output": "Something else",
                    "graders": {
                        "faithfulness": {"pass": True},
                        "source_retrieval": {"pass": False},
                    },
                },
                {
                    "test_id": "ok",
                    "pass": True,
                    "output": "All good",
                    "graders": {
                        "faithfulness": {"pass": True},
                        "source_retrieval": {"pass": True},
                    },
                },
            ],
        },
    )
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_classify_failures_grader_only_no_llm(
    client, auth_headers, db_session, test_project
):
    """Without an LLM configured, every failure gets a grader-derived pattern."""
    run_id = await _seed_run_with_failures(client, auth_headers, db_session, test_project)

    resp = await client.post(
        f"/api/evals/{run_id}/classify-failures",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["classified"] == 2
    assert body["failure_pattern_summary"] == {
        "faithfulness": 1,
        "source_retrieval": 1,
    }

    # Pattern fields are surfaced on the run detail.
    detail = (await client.get(f"/api/evals/{run_id}", headers=auth_headers)).json()
    by_test = {r["test_id"]: r for r in detail["results"]}
    assert by_test["fail-faith"]["failure_pattern"] == "faithfulness"
    assert by_test["fail-faith"]["grader_pattern"] == ["faithfulness"]
    assert by_test["fail-source"]["failure_pattern"] == "source_retrieval"
    assert by_test["ok"]["failure_pattern"] is None
    assert by_test["ok"]["grader_pattern"] == []
    assert detail["metadata"]["failure_pattern_summary"] == {
        "faithfulness": 1,
        "source_retrieval": 1,
    }


@pytest.mark.asyncio
async def test_classify_failures_run_not_found(client, auth_headers):
    fake = uuid4()
    resp = await client.post(
        f"/api/evals/{fake}/classify-failures",
        headers=auth_headers,
    )
    assert resp.status_code == 404
