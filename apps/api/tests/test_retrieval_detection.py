"""Tests for retrieval-source config helpers, detection parsing, and endpoint."""

from __future__ import annotations

import json

import pytest

from app.models.project import Project
from app.services.retrieval_config import (
    DEFAULT_RETRIEVAL_SPAN_NAME,
    extract_retrieval_context_from_payload,
    get_retrieval_payload_key,
    get_retrieval_source,
    get_retrieval_span_name,
)
from app.services.retrieval_detection import _parse_suggestion


# --- extract_retrieval_context_from_payload ---

def test_extract_prefers_configured_key():
    parsed = {"retrievedContext": "ctx", "context": "other"}
    assert extract_retrieval_context_from_payload(parsed, payload_key="retrievedContext") == "ctx"


def test_extract_falls_back_to_default_keys_when_unconfigured():
    assert extract_retrieval_context_from_payload({"retrievalContext": "c"}) == "c"
    assert extract_retrieval_context_from_payload({"context": "c"}) == "c"
    # Common RAG payload shapes work without any configured key — critical for
    # eval runs against a live endpoint, where span-kind config doesn't apply.
    assert extract_retrieval_context_from_payload({"retrievedContext": "c"}) == "c"
    assert extract_retrieval_context_from_payload({"formattedContext": "c"}) == "c"
    out = extract_retrieval_context_from_payload({"searchSources": [{"a": 1}]})
    assert json.loads(out) == [{"a": 1}]


def test_extract_fallback_order_prefers_specific_over_generic():
    parsed = {"context": "generic", "formattedContext": "specific"}
    assert extract_retrieval_context_from_payload(parsed) == "specific"


def test_extract_serializes_list_and_dict():
    out = extract_retrieval_context_from_payload({"searchSources": [{"a": 1}]}, payload_key="searchSources")
    assert json.loads(out) == [{"a": 1}]


def test_extract_returns_none_when_no_match():
    assert extract_retrieval_context_from_payload({"foo": "bar"}, payload_key="baz") is None
    assert extract_retrieval_context_from_payload("not a dict") is None


def test_extract_truncates():
    big = "x" * 50000
    out = extract_retrieval_context_from_payload({"context": big})
    assert len(out) == 10000


# --- config resolution: structured vs legacy vs default ---

def test_span_name_from_structured_source():
    p = Project(settings={"retrieval_source": {"kind": "span", "value": "my-rag"}})
    assert get_retrieval_span_name(p) == "my-rag"
    assert get_retrieval_payload_key(p) is None


def test_payload_key_from_structured_source():
    p = Project(settings={"retrieval_source": {"kind": "payload_key", "value": "retrievedContext"}})
    assert get_retrieval_payload_key(p) == "retrievedContext"
    # span-name falls back to default so span-based analytics keep working
    assert get_retrieval_span_name(p) == DEFAULT_RETRIEVAL_SPAN_NAME


def test_legacy_span_name_key_still_honored():
    p = Project(settings={"retrieval_span_name": "legacy-span"})
    assert get_retrieval_span_name(p) == "legacy-span"
    assert get_retrieval_source(p) is None


def test_default_span_name_when_unset():
    assert get_retrieval_span_name(Project(settings={})) == DEFAULT_RETRIEVAL_SPAN_NAME


def test_invalid_source_ignored():
    p = Project(settings={"retrieval_source": {"kind": "bogus", "value": "x"}})
    assert get_retrieval_source(p) is None
    assert get_retrieval_span_name(p) == DEFAULT_RETRIEVAL_SPAN_NAME


# --- _parse_suggestion validation ---

_PAYLOAD = [{"key": "retrievedContext", "sample": "str: ..."}]
_SPANS = [{"name": "rag-step (tool)", "sample": "..."}]


def test_parse_accepts_valid_payload_key():
    out = _parse_suggestion(
        json.dumps({"kind": "payload_key", "value": "retrievedContext", "confidence": "high"}),
        _PAYLOAD, _SPANS,
    )
    assert out == {"kind": "payload_key", "value": "retrievedContext", "confidence": "high", "reasoning": None}


def test_parse_matches_span_name_ignoring_type_suffix():
    out = _parse_suggestion(
        json.dumps({"kind": "span", "value": "rag-step", "confidence": "medium"}),
        _PAYLOAD, _SPANS,
    )
    assert out["kind"] == "span" and out["value"] == "rag-step"


def test_parse_rejects_hallucinated_value():
    assert _parse_suggestion(
        json.dumps({"kind": "payload_key", "value": "nonexistent", "confidence": "high"}),
        _PAYLOAD, _SPANS,
    ) is None


def test_parse_handles_none_and_garbage():
    assert _parse_suggestion(json.dumps({"kind": "none"}), _PAYLOAD, _SPANS) is None
    assert _parse_suggestion("not json", _PAYLOAD, _SPANS) is None


def test_parse_defaults_bad_confidence_to_low():
    out = _parse_suggestion(
        json.dumps({"kind": "payload_key", "value": "retrievedContext", "confidence": "bogus"}),
        _PAYLOAD, _SPANS,
    )
    assert out["confidence"] == "low"


# --- endpoint ---

@pytest.mark.asyncio
async def test_detect_endpoint_owner_gated(client, auth_headers, db_session):
    """A non-owner project id returns 404 (owner-scoped query)."""
    from uuid import uuid4

    resp = await client.post(
        f"/api/projects/{uuid4()}/detect-retrieval-source", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_detect_endpoint_success(client, auth_headers, test_project, monkeypatch):
    """Owner gets the suggestion; LLM + detection are stubbed."""
    import app.routers.projects as projects_router

    class _FakeLlm:
        provider = "openai"
        model = "gpt-test"

        def __init__(self, *a, **k):
            pass

    async def _fake_detect(db, project, llm):
        return {
            "suggestion": {
                "kind": "payload_key", "value": "retrievedContext",
                "confidence": "high", "reasoning": "holds the chunks",
            },
            "candidates": {"payload_keys": [{"key": "retrievedContext", "sample": "str: ..."}], "spans": []},
            "usage": None,
        }

    monkeypatch.setattr(projects_router, "AnalysisLlmService", _FakeLlm)
    monkeypatch.setattr(projects_router, "detect_retrieval_source", _fake_detect)

    resp = await client.post(
        f"/api/projects/{test_project.id}/detect-retrieval-source", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggestion"]["value"] == "retrievedContext"
    assert body["candidates"]["payload_keys"][0]["key"] == "retrievedContext"
