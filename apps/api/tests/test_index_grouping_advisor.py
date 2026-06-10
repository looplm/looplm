"""Tests for the index grouping advisor (Data Sources LLM hierarchy suggestions).

Profiling heuristics + LLM-output sanitization are pure Python, so they run on
the SQLite test stack without Azure or a real LLM.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.index_providers.base import BaseIndexProvider, PartitionKey, PartitionValue
from app.services.analysis_llm import LlmUsageInfo
from app.services.index_grouping_advisor import (
    _looks_like_path,
    _no_em_dash,
    _parse,
    suggest_grouping,
)


def _pv(pairs):
    return [PartitionValue(value=v, doc_count=c) for v, c in pairs]


def test_looks_like_path_detects_breadcrumbs():
    breadcrumb = _pv(
        [
            ("Klare Startseite > Übersicht > Wissensdatenbank", 5),
            ("Klare Startseite > Externe Daten > Klara", 3),
        ]
    )
    assert _looks_like_path(breadcrumb) is True


def test_looks_like_path_false_for_flat_labels():
    flat = _pv([("confluence", 100), ("slack", 40), ("jira", 10)])
    assert _looks_like_path(flat) is False


def test_parse_clamps_hallucinated_keys_and_dedupes():
    raw = json.dumps(
        {
            "suggested_levels": [["source_type", "made_up", "source_type"], ["space"]],
            "summary": "Group by source then space.",
            "levels": [
                {"keys": ["source_type", "made_up"], "reason": "few values"},
                {"keys": ["ghost"], "reason": "x"},
            ],
            "hints": [],
        }
    )
    result = _parse(raw, valid_keys=["source_type", "space", "page_id"])
    assert result.suggested_levels == [["source_type"], ["space"]]
    # levels are clamped to keys that survived in suggested_levels
    assert [lvl.keys for lvl in result.levels] == [["source_type"]]


def test_parse_keeps_parallel_level():
    raw = json.dumps(
        {"suggested_levels": [["source_type"], ["tags", "team"]], "hints": []}
    )
    result = _parse(raw, valid_keys=["source_type", "tags", "team"])
    assert result.suggested_levels == [["source_type"], ["tags", "team"]]


def test_parse_falls_back_to_first_key_when_empty():
    raw = json.dumps({"suggested_levels": [["ghost"]], "summary": "", "hints": []})
    result = _parse(raw, valid_keys=["source_type", "space"])
    assert result.suggested_levels == [["source_type"]]


def test_parse_strips_em_dashes():
    raw = json.dumps(
        {
            "suggested_levels": [["source_type"]],
            "summary": "Browse by source — the cleanest split.",
            "hints": [
                {"severity": "warning", "title": "Path field — fix it",
                 "message": "Split it — into parts.", "suggested_field": "level_1"},
            ],
        }
    )
    result = _parse(raw, valid_keys=["source_type"])
    assert "—" not in result.summary
    assert "—" not in result.hints[0].title
    assert "—" not in result.hints[0].message


def test_parse_sanitizes_hint_severity_and_drops_blank():
    raw = json.dumps(
        {
            "suggested_levels": [["source_type"]],
            "hints": [
                {"severity": "critical", "title": "Path field", "message": "split it",
                 "suggested_field": "level_1"},
                {"severity": "info", "title": "", "message": ""},
            ],
        }
    )
    result = _parse(raw, valid_keys=["source_type"])
    assert len(result.hints) == 1
    assert result.hints[0].severity == "info"  # unknown severity coerced
    assert result.hints[0].suggested_field == "level_1"


def test_parse_handles_non_json():
    result = _parse("not json at all", valid_keys=["source_type"])
    assert result.suggested_levels == [["source_type"]]


def test_no_em_dash_replaces_with_comma():
    assert _no_em_dash("a — b") == "a, b"
    assert _no_em_dash("ends with —") == "ends with"


class _FakeProvider(BaseIndexProvider):
    def __init__(self, dist):
        self._dist = dist

    async def test_connection(self) -> int:
        return 1000

    async def list_partition_keys(self):
        return [
            PartitionKey(key="source_type", label="source_type", metadata={"type": "Edm.String"}),
            PartitionKey(key="breadcrumb", label="breadcrumb", metadata={"type": "Edm.String"}),
        ]

    async def get_partition_distribution(self, key, filters=None):
        return self._dist[key]

    async def sample_documents(self, key, value, n, filters=None):
        return []


@pytest.mark.asyncio
async def test_suggest_grouping_end_to_end(db_session, test_project):
    fake = _FakeProvider(
        {
            "source_type": _pv([("confluence", 600), ("slack", 400)]),
            "breadcrumb": _pv([("A > B > C", 1), ("D > E > F", 1)]),
        }
    )
    llm_json = json.dumps(
        {
            "suggested_levels": [["source_type", "hallucinated"]],
            "summary": "Browse by source type.",
            "levels": [{"keys": ["source_type"], "reason": "low cardinality"}],
            "hints": [
                {
                    "severity": "warning",
                    "title": "Path-encoded field",
                    "message": "Split breadcrumb into separate fields.",
                    "field": "breadcrumb",
                    "suggested_field": "level_1",
                }
            ],
        }
    )
    usage = LlmUsageInfo(
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        cost_usd=0.0,
        cached_tokens=0,
        reasoning_tokens=0,
        duration_ms=5,
    )

    with patch("app.services.analysis_llm.AnalysisLlmService") as MockLLM:
        instance = MockLLM.return_value
        instance.provider = "openai"
        instance.model = "gpt-test"
        instance.tracked_chat_completion = AsyncMock(return_value=(llm_json, usage))

        suggestion, model = await suggest_grouping(
            fake, project_id=test_project.id, db=db_session
        )

    assert model == "gpt-test"
    # Hallucinated key dropped; breadcrumb never suggested as a grouping dimension.
    assert suggestion.suggested_levels == [["source_type"]]
    assert any(h.suggested_field == "level_1" for h in suggestion.hints)
