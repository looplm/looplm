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

    # One retriever span per day across two days.
    assert len(data) == 2
    assert {p["date"] for p in data} == {"2025-01-01", "2025-01-02"}
    assert all(p["count"] == 1 for p in data)
    assert sum(p["tokens_in"] + p["tokens_out"] for p in data) == 95


@pytest.mark.asyncio
async def test_request_clusters_requires_minimum(client, db_session, test_integration, headers):
    """With fewer than 5 extractable requests, the POST is rejected (before any LLM call)."""
    await _seed_retrieval(db_session, test_integration)  # only 2 traces with input

    resp = await client.post("/api/analytics/request-clusters", headers=headers, json={"limit": 300})
    # Either LLM is unconfigured (400) or too few requests (400) — both are 400 with detail.
    assert resp.status_code == 400
