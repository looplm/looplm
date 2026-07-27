"""Tests for the custom-agent retrieval probe (agent_retrieval)."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.services import agent_retrieval
from app.services.agent_retrieval import (
    DEFAULT_AGENT_LABEL,
    get_agent_retrieval_config,
    probe_agent_chunk_ids,
)
from app.services.retrieval_config import extract_retrieved_chunks


def test_get_config_none_when_unset():
    assert get_agent_retrieval_config(None) is None
    assert get_agent_retrieval_config({}) is None
    assert get_agent_retrieval_config({"agent_retrieval_endpoint": "   "}) is None


def test_get_config_resolves_fields():
    cfg = get_agent_retrieval_config(
        {
            "agent_retrieval_endpoint": " https://rde/api/chat/retrieval ",
            "agent_retrieval_token": " secret ",
            "agent_retrieval_label": " RDE-GPT agent ",
        }
    )
    assert cfg is not None
    assert cfg.endpoint == "https://rde/api/chat/retrieval"
    assert cfg.token == "secret"
    assert cfg.label == "RDE-GPT agent"
    # Default request template when none configured.
    assert cfg.request_template == {"messages": [{"role": "user", "content": "{prompt}"}]}


def test_get_config_default_label():
    cfg = get_agent_retrieval_config({"agent_retrieval_endpoint": "https://x"})
    assert cfg is not None
    assert cfg.label == DEFAULT_AGENT_LABEL
    assert cfg.token is None


def test_extract_retrieved_chunks_reads_ranked_chunks():
    """The retrieval endpoint's chunk-level rankedChunks are parsed in rank order."""
    payload = {
        "rankedChunks": [
            {"rank": 1, "id": "page_10_chunk_0", "title": "A", "url": "u1", "score": 3.2},
            {"rank": 2, "id": "page_10_chunk_1", "title": "B", "url": "u2", "score": 2.1},
        ],
        # searchSources (page-deduped) must be ignored in favour of rankedChunks.
        "searchSources": [{"id": "page_10_chunk_0", "title": "A"}],
    }
    chunks = extract_retrieved_chunks(payload)
    assert [c["chunk_id"] for c in chunks] == ["page_10_chunk_0", "page_10_chunk_1"]


@pytest.mark.asyncio
async def test_probe_returns_ranked_ids(monkeypatch):
    cfg = get_agent_retrieval_config({"agent_retrieval_endpoint": "https://x", "agent_retrieval_token": "t"})
    raw = json.dumps(
        {
            "rankedChunks": [
                {"id": "page_1_chunk_0", "score": 3.0},
                {"id": "page_2_chunk_0", "score": 2.0},
            ],
            "retrievalDiagnostics": {"retrievalMode": "hybrid"},
        }
    )

    async def fake_call(*args, **kwargs):
        return ("", raw, 12)

    monkeypatch.setattr(agent_retrieval, "_call_target_api", fake_call)
    monkeypatch.setattr(agent_retrieval, "cache_get_json", lambda *a, **k: _none())
    monkeypatch.setattr(agent_retrieval, "cache_set_json", lambda *a, **k: _none())

    ids = await probe_agent_chunk_ids(None, cfg, uuid4(), "t1", "some query", 50, refresh=True)
    assert ids == ["page_1_chunk_0", "page_2_chunk_0"]


@pytest.mark.asyncio
async def test_probe_skips_degraded_run(monkeypatch):
    cfg = get_agent_retrieval_config({"agent_retrieval_endpoint": "https://x"})
    raw = json.dumps(
        {
            "rankedChunks": [{"id": "page_1_chunk_0"}],
            "retrievalDiagnostics": {"retrievalMode": "keyword-fallback"},
        }
    )

    async def fake_call(*args, **kwargs):
        return ("", raw, 12)

    monkeypatch.setattr(agent_retrieval, "_call_target_api", fake_call)
    monkeypatch.setattr(agent_retrieval, "cache_get_json", lambda *a, **k: _none())
    monkeypatch.setattr(agent_retrieval, "cache_set_json", lambda *a, **k: _none())

    ids = await probe_agent_chunk_ids(None, cfg, uuid4(), "t1", "q", 50, refresh=True)
    assert ids == []


@pytest.mark.asyncio
async def test_probe_swallows_errors(monkeypatch):
    cfg = get_agent_retrieval_config({"agent_retrieval_endpoint": "https://x"})

    async def boom(*args, **kwargs):
        raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(agent_retrieval, "_call_target_api", boom)
    monkeypatch.setattr(agent_retrieval, "cache_get_json", lambda *a, **k: _none())

    ids = await probe_agent_chunk_ids(None, cfg, uuid4(), "t1", "q", 50, refresh=True)
    assert ids == []


@pytest.mark.asyncio
async def test_probe_empty_query_short_circuits(monkeypatch):
    cfg = get_agent_retrieval_config({"agent_retrieval_endpoint": "https://x"})

    async def should_not_call(*args, **kwargs):  # pragma: no cover
        raise AssertionError("should not call the endpoint for an empty query")

    monkeypatch.setattr(agent_retrieval, "_call_target_api", should_not_call)
    assert await probe_agent_chunk_ids(None, cfg, uuid4(), "t1", "   ", 50) == []


async def _none():
    return None


def test_get_config_pool_flag_defaults_off():
    cfg = get_agent_retrieval_config({"agent_retrieval_endpoint": "https://x"})
    assert cfg is not None and cfg.pool_candidates is False
    on = get_agent_retrieval_config(
        {"agent_retrieval_endpoint": "https://x", "agent_retrieval_pool": True}
    )
    assert on is not None and on.pool_candidates is True


@pytest.mark.asyncio
async def test_probe_chunks_returns_records_for_pooling(monkeypatch):
    """The pooling path needs title/url/preview, not just ids, to render a judgeable candidate."""
    cfg = get_agent_retrieval_config({"agent_retrieval_endpoint": "https://x"})
    raw = json.dumps(
        {
            "rankedChunks": [
                {"id": "page_1_chunk_0", "title": "A", "url": "u1", "content": "body", "score": 3.0}
            ],
            "retrievalDiagnostics": {"retrievalMode": "hybrid"},
        }
    )
    stored: dict = {}

    async def fake_call(*args, **kwargs):
        return ("", raw, 12)

    async def fake_set(key, value, ttl_seconds=None):
        stored[key] = value

    monkeypatch.setattr(agent_retrieval, "_call_target_api", fake_call)
    monkeypatch.setattr(agent_retrieval, "cache_get_json", lambda *a, **k: _none())
    monkeypatch.setattr(agent_retrieval, "cache_set_json", fake_set)

    chunks = await agent_retrieval.probe_agent_chunks(
        None, cfg, uuid4(), "t1", "q", 50, refresh=True
    )
    assert [c["chunk_id"] for c in chunks] == ["page_1_chunk_0"]
    assert chunks[0]["title"] == "A" and chunks[0]["url"] == "u1"
    # Cached in the record shape so the labeling pool can reuse the metrics run's probe.
    assert list(stored.values())[0] == {"chunks": chunks}


@pytest.mark.asyncio
async def test_probe_ids_read_legacy_id_only_cache(monkeypatch):
    """Entries written before pooling existed hold only chunk_ids; the ids path still uses them."""
    cfg = get_agent_retrieval_config({"agent_retrieval_endpoint": "https://x"})

    async def cached(*args, **kwargs):
        return {"chunk_ids": ["a", "b"]}

    async def should_not_call(*args, **kwargs):  # pragma: no cover
        raise AssertionError("must not re-probe when a legacy cache entry exists")

    monkeypatch.setattr(agent_retrieval, "cache_get_json", cached)
    monkeypatch.setattr(agent_retrieval, "_call_target_api", should_not_call)

    assert await probe_agent_chunk_ids(None, cfg, uuid4(), "t1", "q", 50) == ["a", "b"]
