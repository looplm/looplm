"""Tests for the agentic query planner (services/query_planner.py)."""

from __future__ import annotations

import pytest

from app.services.analysis_llm import LlmUsageInfo
from app.services.query_planner import _parse_queries, plan_queries


def _usage() -> LlmUsageInfo:
    return LlmUsageInfo(
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        cost_usd=0.0,
        cached_tokens=0,
        reasoning_tokens=0,
        duration_ms=1,
    )


class FakeLlm:
    """Stand-in for AnalysisLlmService that returns a canned completion."""

    def __init__(self, content: str):
        self._content = content
        self.last_messages: list[dict[str, str]] | None = None

    async def tracked_chat_completion(self, messages, *, temperature=0.2, response_format=None):
        self.last_messages = messages
        return self._content, _usage()


def test_parse_queries_dedupes_case_insensitively_and_trims():
    out = _parse_queries('{"queries": [" A query ", "a QUERY", "Second", ""]}')
    assert out == ["A query", "Second"]


def test_parse_queries_tolerates_code_fence():
    out = _parse_queries('```json\n{"queries": ["one", "two"]}\n```')
    assert out == ["one", "two"]


def test_parse_queries_returns_empty_on_garbage():
    assert _parse_queries("not json at all") == []
    assert _parse_queries('{"queries": "nope"}') == []


@pytest.mark.asyncio
async def test_plan_queries_caps_and_passes_instructions():
    llm = FakeLlm('{"queries": ["q1", "q2", "q3", "q4"]}')
    queries, usage = await plan_queries(
        llm, "How do I do X?", instructions="CUSTOM RUBRIC", max_queries=2
    )
    assert queries == ["q1", "q2"]
    assert usage.total_tokens == 2
    assert llm.last_messages[0] == {"role": "system", "content": "CUSTOM RUBRIC"}
    assert "How do I do X?" in llm.last_messages[1]["content"]


@pytest.mark.asyncio
async def test_plan_queries_empty_reply_yields_no_queries():
    llm = FakeLlm("{}")
    queries, _ = await plan_queries(llm, "q")
    assert queries == []
