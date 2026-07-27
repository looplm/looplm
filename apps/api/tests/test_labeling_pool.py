"""Tests for per-case labeling-pool assembly (services/labeling_pool.py).

Focus: the opt-in custom-agent head, which decides whether the agent's own candidates get
judged or silently count as misses in the by-stage metrics.
"""

from __future__ import annotations

import pytest

from app.models.project import Project
from app.services import labeling_pool


@pytest.fixture(autouse=True)
def _no_cache_or_index(monkeypatch):
    """Run pools fresh: no Redis, no index provider, no embeddings."""

    async def _none(*args, **kwargs):
        return None

    monkeypatch.setattr(labeling_pool, "cache_get_json", _none)
    monkeypatch.setattr(labeling_pool, "cache_set_json", _none)
    monkeypatch.setattr(labeling_pool, "embed_query", _none)


def _agent_settings(**overrides) -> dict:
    return {
        "agent_retrieval_endpoint": "https://agent/api/chat/retrieval",
        "agent_retrieval_pool": True,
        **overrides,
    }


@pytest.mark.asyncio
async def test_agent_chunks_join_the_pool_when_enabled(db_session, test_project: Project, monkeypatch):
    test_project.settings = _agent_settings()
    probed: dict = {}

    async def fake_probe(client, config, project_id, test_id, query, n, *, refresh=False):
        probed["depth"] = n
        return [{"chunk_id": f"agent_{i}"} for i in range(20)]

    monkeypatch.setattr(labeling_pool, "probe_agent_chunks", fake_probe)

    pool, _computed, connected = await labeling_pool.assemble_case_pool(
        db_session, test_project, "t1", "how do I do X?"
    )

    assert connected is False  # no index provider in this project
    assert "agent" in pool.heads_ran
    # Probed at the shared depth (one cached ranking per case), pooled at the per-head depth so
    # the agent contributes the same number of candidates as every other head.
    assert probed["depth"] == labeling_pool.AGENT_PROBE_DEPTH
    assert [c.chunk_id for c in pool.chunks] == [f"agent_{i}" for i in range(10)]
    assert pool.chunks[0].ranks == {"agent": 1}


@pytest.mark.asyncio
async def test_agent_not_probed_when_pooling_is_off(db_session, test_project: Project, monkeypatch):
    test_project.settings = _agent_settings(agent_retrieval_pool=False)

    async def should_not_call(*args, **kwargs):  # pragma: no cover
        raise AssertionError("agent must not be probed unless the project opts in")

    monkeypatch.setattr(labeling_pool, "probe_agent_chunks", should_not_call)

    pool, _computed, _connected = await labeling_pool.assemble_case_pool(
        db_session, test_project, "t1", "q"
    )
    assert pool.heads_ran == []
    assert pool.chunks == []


@pytest.mark.asyncio
async def test_unreachable_agent_is_reported_not_fatal(db_session, test_project: Project, monkeypatch):
    test_project.settings = _agent_settings()

    async def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(labeling_pool, "probe_agent_chunks", boom)

    pool, _computed, _connected = await labeling_pool.assemble_case_pool(
        db_session, test_project, "t1", "q"
    )
    assert "agent" not in pool.heads_ran
    assert "connection refused" in pool.heads_failed["agent"]


@pytest.mark.asyncio
async def test_empty_agent_ranking_is_reported(db_session, test_project: Project, monkeypatch):
    """A degraded/unreachable probe returns nothing; say so rather than pooling a short set."""
    test_project.settings = _agent_settings()

    async def empty(*args, **kwargs):
        return []

    monkeypatch.setattr(labeling_pool, "probe_agent_chunks", empty)

    pool, _computed, _connected = await labeling_pool.assemble_case_pool(
        db_session, test_project, "t1", "q"
    )
    assert pool.heads_failed["agent"] == "agent returned no ranking for this query"


def test_agent_pool_gets_its_own_cache_key(test_project: Project):
    """Turning the head on changes the candidate set, so the two pools must not share a key."""
    base = labeling_pool._pool_cache_key(test_project.id, "t1", 10, "0")
    with_agent = labeling_pool._pool_cache_key(test_project.id, "t1", 10, "0", with_agent=True)
    assert base != with_agent
    # Off → byte-identical to the keys written before the head existed.
    assert base == f"labeling:pool:{test_project.id}:t1:10:0"
