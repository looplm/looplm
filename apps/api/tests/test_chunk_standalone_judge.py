"""Unit tests for the standalone-interpretability judge (fake LLM, no network)."""

import json

import pytest

from app.services.analysis_llm import LlmUsageInfo
from app.services.chunk_judge_common import AiJudgeChunk, batch_chunks
from app.services.chunk_standalone_judge import (
    _parse_verdicts,
    judge_standalone,
    summarize_standalone,
)


def _usage(tokens=10):
    return LlmUsageInfo(
        input_tokens=tokens, output_tokens=tokens, total_tokens=2 * tokens,
        cost_usd=0.001, cached_tokens=0, reasoning_tokens=0, duration_ms=5,
    )


class FakeLlm:
    """Returns queued responses; records how many calls were made."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def tracked_chat_completion(self, messages, *, temperature=0.2, response_format=None):
        self.calls += 1
        return self._responses.pop(0), _usage()


# ── Parsing ──────────────────────────────────────────────────────────────────

def test_parse_verdicts_plain_json():
    content = json.dumps({"verdicts": [
        {"chunk": 1, "standalone": True, "reason": "self-contained"},
        {"chunk": 2, "standalone": False, "reason": "dangling reference"},
    ]})
    out = _parse_verdicts(content, 2)
    assert out[1].standalone is True
    assert out[2].standalone is False
    assert out[2].reason == "dangling reference"


def test_parse_verdicts_tolerates_fences_and_prose():
    content = 'Here you go:\n```json\n{"verdicts": [{"chunk": 1, "standalone": false, "reason": "x"}]}\n```'
    out = _parse_verdicts(content, 1)
    assert out[1].standalone is False


def test_parse_verdicts_drops_invalid_entries():
    content = json.dumps({"verdicts": [
        {"chunk": 99, "standalone": True},        # out of range
        {"chunk": 1, "standalone": "yes"},        # not a bool
        {"chunk": True, "standalone": False},     # bool masquerading as int
        "garbage",
    ]})
    assert _parse_verdicts(content, 2) == {}


# ── Judge ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_judge_maps_verdicts_to_chunk_ids():
    chunks = [AiJudgeChunk("a", "Complete text."), AiJudgeChunk("b", "in this case halve it")]
    llm = FakeLlm([json.dumps({"verdicts": [
        {"chunk": 1, "standalone": True, "reason": ""},
        {"chunk": 2, "standalone": False, "reason": "no antecedent"},
    ]})])
    verdicts, usage = await judge_standalone(llm, chunks)
    assert verdicts["a"].standalone and not verdicts["b"].standalone
    assert usage.total_tokens == 20
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_judge_batches_and_accumulates_usage(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ai_judge_max_batch_chunks", 1)
    chunks = [AiJudgeChunk("a", "One."), AiJudgeChunk("b", "Two.")]
    response = json.dumps({"verdicts": [{"chunk": 1, "standalone": True, "reason": ""}]})
    llm = FakeLlm([response, response])
    verdicts, usage = await judge_standalone(llm, chunks)
    assert llm.calls == 2
    assert set(verdicts) == {"a", "b"}
    assert usage.total_tokens == 40
    assert usage.cost_usd == pytest.approx(0.002)


@pytest.mark.asyncio
async def test_omitted_chunks_stay_unjudged():
    chunks = [AiJudgeChunk("a", "One."), AiJudgeChunk("b", "Two.")]
    llm = FakeLlm([json.dumps({"verdicts": [{"chunk": 2, "standalone": False, "reason": "x"}]})])
    verdicts, _ = await judge_standalone(llm, chunks)
    assert "a" not in verdicts and verdicts["b"].standalone is False


def test_batch_chunks_respects_budget(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ai_judge_context_tokens", 120)
    monkeypatch.setattr(settings, "ai_judge_response_reserve_tokens", 0)
    monkeypatch.setattr(settings, "ai_judge_chars_per_token", 4.0)
    chunks = [AiJudgeChunk(str(i), "x" * 200) for i in range(4)]  # ~58 tokens each w/ overhead
    batches = batch_chunks(chunks, fixed_texts=("",))
    assert len(batches) == 2
    assert all(len(b) == 2 for b in batches)


# ── Summary ──────────────────────────────────────────────────────────────────

def test_summarize_counts_and_flags():
    from app.services.chunk_standalone_judge import StandaloneVerdict

    verdicts = {f"c{i}": StandaloneVerdict(standalone=i >= 5, reason="r") for i in range(10)}
    metrics, findings = summarize_standalone(verdicts, sampled=12, texts_by_id={"c0": "text zero"})
    assert metrics["sampled"] == 12
    assert metrics["judged"] == 10
    assert metrics["dependent"] == 5
    assert metrics["dependent_pct"] == 50.0
    assert metrics["examples"][0]["chunk_id"].startswith("c")
    # 50% dependent crosses the critical threshold (40%).
    assert findings and findings[0].severity == "critical"


def test_summarize_below_threshold_has_no_finding():
    from app.services.chunk_standalone_judge import StandaloneVerdict

    verdicts = {f"c{i}": StandaloneVerdict(standalone=i > 0, reason="") for i in range(10)}
    metrics, findings = summarize_standalone(verdicts, sampled=10)
    assert metrics["dependent_pct"] == 10.0
    assert findings == []
