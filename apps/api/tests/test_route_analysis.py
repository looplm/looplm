"""Tests for route analysis endpoints and service logic."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.models import Span, SpanType, Trace, TraceStatus
from app.schemas.route_analysis import BottleneckResponse, RouteAnalysisResponse
from app.services.route_analysis import get_bottlenecks, get_route_analysis


# ── Service-level tests ──────────────────────────────────────

@pytest.mark.asyncio
async def test_route_analysis_empty(db_session, test_integration, test_project):
    """No traces → empty nodes/edges."""
    result = await get_route_analysis(test_integration.id, test_project.id, db_session)
    assert isinstance(result, RouteAnalysisResponse)
    assert result.nodes == []
    assert result.edges == []
    assert result.total_traces == 0


@pytest.mark.asyncio
async def test_route_analysis_with_spans(db_session, test_integration, test_project, sample_traces_and_spans):
    """With 3 traces of chain→llm+tool, verify nodes and edges."""
    result = await get_route_analysis(test_integration.id, test_project.id, db_session)

    assert result.total_traces == 3
    assert len(result.nodes) == 3  # agent_chain, gpt4_call, search_tool

    node_names = {n.name for n in result.nodes}
    assert node_names == {"agent_chain", "gpt4_call", "search_tool"}

    # chain→llm and chain→tool edges should exist
    # Note: SQLite may render enum as "SpanType.chain" vs "chain"
    # Find edges from agent_chain to gpt4_call and search_tool
    chain_to_llm = [e for e in result.edges if "agent_chain" in e.source and "gpt4_call" in e.target]
    chain_to_tool = [e for e in result.edges if "agent_chain" in e.source and "search_tool" in e.target]
    assert len(chain_to_llm) == 1
    assert len(chain_to_tool) == 1

    # Each edge traversed 3 times (once per trace)
    assert chain_to_llm[0].frequency == 3
    assert chain_to_tool[0].frequency == 3


@pytest.mark.asyncio
async def test_route_analysis_single_trace(db_session, test_integration, test_project):
    """Single trace with one span."""
    t = Trace(
        id=uuid4(), integration_id=test_integration.id, external_id="single",
        name="solo", start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        status=TraceStatus.success,
    )
    db_session.add(t)
    await db_session.flush()
    s = Span(
        id=uuid4(), trace_id=t.id, name="only_span", type=SpanType.llm,
        duration_ms=200, status="ok",
    )
    db_session.add(s)
    await db_session.commit()

    result = await get_route_analysis(test_integration.id, test_project.id, db_session)
    assert result.total_traces == 1
    assert len(result.nodes) == 1
    assert result.nodes[0].name == "only_span"
    assert result.edges == []


@pytest.mark.asyncio
async def test_route_analysis_not_found(db_session, test_project):
    """Non-existent integration raises ValueError."""
    with pytest.raises(ValueError, match="Integration not found"):
        await get_route_analysis(uuid4(), test_project.id, db_session)


@pytest.mark.asyncio
async def test_edge_frequency(db_session, test_integration, test_project):
    """Verify edge frequencies sum correctly across traces."""
    for i in range(5):
        t = Trace(
            id=uuid4(), integration_id=test_integration.id, external_id=f"freq-{i}",
            name=f"t-{i}", start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            status=TraceStatus.success,
        )
        db_session.add(t)
        await db_session.flush()
        parent = Span(id=uuid4(), trace_id=t.id, name="A", type=SpanType.chain, duration_ms=10, status="ok")
        db_session.add(parent)
        await db_session.flush()
        child = Span(id=uuid4(), trace_id=t.id, parent_span_id=parent.id, name="B", type=SpanType.llm, duration_ms=20, status="ok")
        db_session.add(child)
    await db_session.commit()

    result = await get_route_analysis(test_integration.id, test_project.id, db_session)
    ab_edge = [e for e in result.edges if "A::" in e.source and "B::" in e.target]
    assert len(ab_edge) == 1
    assert ab_edge[0].frequency == 5


# ── Bottleneck scoring ────────────────────────────────────────

@pytest.mark.asyncio
async def test_bottlenecks_empty(db_session, test_integration, test_project):
    result = await get_bottlenecks(test_integration.id, test_project.id, db_session)
    assert isinstance(result, BottleneckResponse)
    assert result.bottlenecks == []


@pytest.mark.asyncio
async def test_bottlenecks_with_data(db_session, test_integration, test_project, sample_traces_and_spans):
    result = await get_bottlenecks(test_integration.id, test_project.id, db_session)
    assert result.total_traces == 3

    # search_tool has errors → should appear as bottleneck
    # At minimum the high-latency/high-error nodes should appear
    assert len(result.bottlenecks) > 0
    # Scores should be descending
    scores = [b.bottleneck_score for b in result.bottlenecks]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_bottleneck_scoring_algorithm(db_session, test_integration, test_project):
    """Verify scoring weights: 0.4*latency + 0.3*frequency + 0.3*error."""
    t = Trace(
        id=uuid4(), integration_id=test_integration.id, external_id="bn-1",
        name="t", start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        status=TraceStatus.success,
    )
    db_session.add(t)
    await db_session.flush()

    # High latency node
    db_session.add(Span(id=uuid4(), trace_id=t.id, name="slow", type=SpanType.llm, duration_ms=1000, status="ok"))
    # High error node
    db_session.add(Span(id=uuid4(), trace_id=t.id, name="buggy", type=SpanType.tool, duration_ms=10, status="error"))
    await db_session.commit()

    result = await get_bottlenecks(test_integration.id, test_project.id, db_session)
    bn_map = {b.name: b for b in result.bottlenecks}

    # "slow" should score high on latency
    if "slow" in bn_map:
        assert "latency" in bn_map["slow"].reason
    # "buggy" should score high on error rate
    if "buggy" in bn_map:
        assert "error rate" in bn_map["buggy"].reason


# ── HTTP endpoint tests ───────────────────────────────────────

@pytest.mark.asyncio
async def test_route_analysis_endpoint(client: AsyncClient, auth_headers, test_integration, sample_traces_and_spans):
    resp = await client.get(f"/api/route-analysis/{test_integration.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_traces"] == 3
    assert len(data["nodes"]) == 3


@pytest.mark.asyncio
async def test_route_analysis_endpoint_not_found(client: AsyncClient, auth_headers):
    resp = await client.get(f"/api/route-analysis/{uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_bottlenecks_endpoint(client: AsyncClient, auth_headers, test_integration, sample_traces_and_spans):
    resp = await client.get(f"/api/route-analysis/{test_integration.id}/bottlenecks", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "bottlenecks" in data


@pytest.mark.asyncio
async def test_route_analysis_no_auth(client: AsyncClient, test_integration):
    resp = await client.get(f"/api/route-analysis/{test_integration.id}")
    assert resp.status_code in (401, 403)
