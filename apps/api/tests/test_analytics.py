"""Tests for the Analytics endpoints — retrieval insights + request clustering."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.models import Span, SpanType, Trace, TraceStatus


@pytest.fixture
def headers(auth_headers, test_project):
    return {**auth_headers, "X-Project-Id": str(test_project.id)}


async def _seed_retrieval(db_session, integration):
    """Two traces: one with a retrieval-context + retriever span, one without."""
    t1 = Trace(
        id=uuid4(), integration_id=integration.id, external_id="r1", name="chat",
        input={"messages": [{"role": "user", "content": "How do I cancel my plan?"}]},
        start_time=datetime(2025, 1, 1, tzinfo=timezone.utc), status=TraceStatus.success,
    )
    t2 = Trace(
        id=uuid4(), integration_id=integration.id, external_id="r2", name="chat",
        input={"messages": [{"role": "user", "content": "Where is my invoice?"}]},
        start_time=datetime(2025, 1, 2, tzinfo=timezone.utc), status=TraceStatus.failure,
    )
    db_session.add_all([t1, t2])
    await db_session.flush()

    db_session.add_all([
        Span(
            id=uuid4(), trace_id=t1.id, name="retrieval-context", type=SpanType.retriever,
            duration_ms=120, tokens_in=50, tokens_out=10, status="ok",
            output={"sources": [{"url": "https://docs.example.com/billing"}, {"url": "https://docs.example.com/plans"}]},
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
        Span(
            id=uuid4(), trace_id=t2.id, name="retrieval-context", type=SpanType.retriever,
            duration_ms=80, tokens_in=30, tokens_out=5, status="ok",
            output={"sources": [{"url": "https://docs.example.com/billing"}]},
            created_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        ),
    ])
    await db_session.commit()
    return [t1, t2]


@pytest.mark.asyncio
async def test_retrieval_sources(client, db_session, test_integration, headers):
    await _seed_retrieval(db_session, test_integration)

    resp = await client.get("/api/analytics/retrieval/sources", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    by_url = {s["url"]: s["count"] for s in data}
    # billing appears in both traces, plans in one.
    assert by_url["https://docs.example.com/billing"] == 2
    assert by_url["https://docs.example.com/plans"] == 1
    assert data[0]["url"] == "https://docs.example.com/billing"  # sorted desc
    assert data[0]["domain"] == "docs.example.com"


@pytest.mark.asyncio
async def test_retrieval_activity(client, db_session, test_integration, headers):
    await _seed_retrieval(db_session, test_integration)

    resp = await client.get("/api/analytics/retrieval/activity", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    # Both traces retrieved → full coverage; billing+plans / billing = 1.5 avg sources.
    assert data["requests_total"] == 2
    assert data["requests_with_retrieval"] == 2
    assert data["coverage"] == 1.0
    assert data["avg_sources_per_request"] == 1.5
    # One retrieval span per day across two days.
    assert {p["date"] for p in data["daily"]} == {"2025-01-01", "2025-01-02"}
    assert all(p["count"] == 1 for p in data["daily"])


async def _seed_custom_retrieval(db_session, integration, span_name):
    """A trace whose retrieval step uses a non-default span name and the
    ``chain`` type (mimicking the Langfuse connector, which never tags
    retrieval spans as ``retriever``)."""
    t = Trace(
        id=uuid4(), integration_id=integration.id, external_id="c1", name="chat",
        input={"messages": [{"role": "user", "content": "hi"}]},
        start_time=datetime(2025, 2, 1, tzinfo=timezone.utc), status=TraceStatus.success,
    )
    db_session.add(t)
    await db_session.flush()
    db_session.add(
        Span(
            id=uuid4(), trace_id=t.id, name=span_name, type=SpanType.chain,
            duration_ms=90, tokens_in=12, tokens_out=3, status="ok",
            output={"sources": [{"url": "https://kb.example.com/article"}]},
            created_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        )
    )
    await db_session.commit()
    return t


@pytest.mark.asyncio
async def test_span_names_endpoint(client, db_session, test_integration, headers):
    await _seed_retrieval(db_session, test_integration)

    resp = await client.get("/api/analytics/span-names", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    by_name = {s["name"]: s["count"] for s in data}
    assert by_name["retrieval-context"] == 2


@pytest.mark.asyncio
async def test_retrieval_respects_configured_span_name(
    client, db_session, test_integration, test_project, headers
):
    """A chain-typed span with a custom name is found once the project points its
    retrieval setting at that name — and not under the default name."""
    await _seed_custom_retrieval(db_session, test_integration, "rag_lookup")

    # Default name finds nothing (the span is named rag_lookup, typed chain).
    resp = await client.get("/api/analytics/retrieval/activity", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["requests_with_retrieval"] == 0
    assert resp.json()["coverage"] == 0.0

    # Point the project at the custom span name.
    test_project.settings = {"retrieval_span_name": "rag_lookup"}
    await db_session.commit()

    resp = await client.get("/api/analytics/retrieval/activity", headers=headers)
    assert resp.status_code == 200
    activity = resp.json()
    assert activity["requests_with_retrieval"] == 1
    assert activity["coverage"] == 1.0
    assert len(activity["daily"]) == 1 and activity["daily"][0]["count"] == 1

    resp = await client.get("/api/analytics/retrieval/sources", headers=headers)
    assert resp.status_code == 200
    sources = resp.json()
    assert {s["url"] for s in sources} == {"https://kb.example.com/article"}


async def _seed_multi_hop(db_session, integration):
    """Three traces: a full multi-hop request, a single-pass request, and an
    unclassified one (no metadata, no search span)."""
    t1 = Trace(
        id=uuid4(), integration_id=integration.id, external_id="mh1", name="chat",
        trace_metadata={"queryComplexity": "complex", "expandedQueryCount": 3},
        start_time=datetime(2025, 2, 1, tzinfo=timezone.utc), status=TraceStatus.success,
    )
    t2 = Trace(
        id=uuid4(), integration_id=integration.id, external_id="mh2", name="chat",
        trace_metadata={"queryComplexity": "simple", "expandedQueryCount": 1},
        start_time=datetime(2025, 2, 2, tzinfo=timezone.utc), status=TraceStatus.success,
    )
    t3 = Trace(
        id=uuid4(), integration_id=integration.id, external_id="mh3", name="chat",
        trace_metadata={}, start_time=datetime(2025, 2, 3, tzinfo=timezone.utc),
        status=TraceStatus.success,
    )
    db_session.add_all([t1, t2, t3])
    await db_session.flush()

    db_session.add_all([
        Span(
            id=uuid4(), trace_id=t1.id, name="mandatory-search", type=SpanType.tool,
            input={"queries": ["a", "b", "c"]},
            output={"searchCallCount": 4, "summaryPages": 2},
            created_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        ),
        Span(
            id=uuid4(), trace_id=t2.id, name="mandatory-search", type=SpanType.tool,
            input={"queries": ["a"]},
            output={"searchCallCount": 1, "summaryPages": 0},
            created_at=datetime(2025, 2, 2, tzinfo=timezone.utc),
        ),
    ])
    await db_session.commit()
    return [t1, t2, t3]


@pytest.mark.asyncio
async def test_multi_hop(client, db_session, test_integration, headers):
    await _seed_multi_hop(db_session, test_integration)

    resp = await client.get("/api/analytics/multi-hop", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["requests_total"] == 3
    assert data["requests_analyzed"] == 2  # t3 has no observable signal

    defs = {d["key"]: d for d in data["definitions"]}
    # complex query: t1 multi, t2 simple → 1/2
    assert (defs["complexity"]["multi_hop"], defs["complexity"]["total"]) == (1, 2)
    assert defs["complexity"]["rate"] == 0.5
    # drill-down: both searching requests count; only t1 drilled → 1/2
    assert (defs["drill_down"]["multi_hop"], defs["drill_down"]["total"]) == (1, 2)
    # expansion (>1 query): t1 only → 1/2
    assert (defs["expansion"]["multi_hop"], defs["expansion"]["total"]) == (1, 2)
    # multiple search calls: t1 only → 1/2
    assert (defs["search_calls"]["multi_hop"], defs["search_calls"]["total"]) == (1, 2)

    complexity = {c["level"]: c["count"] for c in data["complexity"]}
    assert complexity == {"simple": 1, "complex": 1, "unclassified": 1}

    assert data["avg_queries_per_request"] == 2.0  # (3 + 1) / 2
    assert data["avg_search_calls_per_request"] == 2.5  # (4 + 1) / 2

    q_bins = {b["value"]: b["count"] for b in data["queries_per_request"]}
    assert q_bins == {1: 1, 3: 1}


@pytest.mark.asyncio
async def test_multi_hop_empty(client, headers):
    """No traces in the window → zeroed response, no error."""
    resp = await client.get("/api/analytics/multi-hop", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["requests_total"] == 0
    assert data["requests_analyzed"] == 0
    assert {d["key"] for d in data["definitions"]} == {
        "complexity", "drill_down", "expansion", "search_calls",
    }
    assert all(d["rate"] is None for d in data["definitions"])


@pytest.mark.asyncio
async def test_request_clusters_requires_minimum(client, db_session, test_integration, headers):
    """With fewer than 5 extractable requests, the POST is rejected (before any LLM call)."""
    await _seed_retrieval(db_session, test_integration)  # only 2 traces with input

    resp = await client.post("/api/analytics/request-clusters", headers=headers, json={"limit": 300})
    # Either LLM is unconfigured (400) or too few requests (400) — both are 400 with detail.
    assert resp.status_code == 400
