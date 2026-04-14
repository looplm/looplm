"""Unit tests for the Langfuse connector with mocked API responses."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from connectors.langfuse.connector import LangfuseConnector

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

SAMPLE_TRACE_SUMMARY = {
    "id": "trace-001",
    "name": "customer-support-agent",
    "timestamp": "2025-01-15T10:30:00Z",
    "input": {"query": "How do I reset my password?"},
    "output": {"answer": "Go to settings and click reset."},
    "sessionId": "sess-abc",
    "userId": "user-42",
    "release": "v1.2.0",
    "version": "1",
    "tags": ["production", "support"],
    "public": False,
    "environment": "production",
    "metadata": {"source": "web"},
}

SAMPLE_OBSERVATION = {
    "id": "obs-001",
    "traceId": "trace-001",
    "type": "GENERATION",
    "name": "llm-call",
    "startTime": "2025-01-15T10:30:01Z",
    "endTime": "2025-01-15T10:30:03Z",
    "model": "gpt-4",
    "input": {"messages": [{"role": "user", "content": "reset password"}]},
    "output": {"content": "Go to settings…"},
    "level": "DEFAULT",
    "parentObservationId": None,
    "usage": {"input": 50, "output": 30, "total": 80},
    "latency": 2.0,
    "metadata": None,
}

SAMPLE_OBSERVATION_ERROR = {
    **SAMPLE_OBSERVATION,
    "id": "obs-002",
    "name": "tool-call",
    "type": "SPAN",
    "level": "ERROR",
    "statusMessage": "Timeout calling external API",
    "latency": 30.0,
}

SAMPLE_TRACE_DETAIL = {
    **SAMPLE_TRACE_SUMMARY,
    "htmlPath": "/project/xxx/traces/trace-001",
    "latency": 2.5,
    "totalCost": 0.003,
    "observations": [SAMPLE_OBSERVATION],
    "scores": [],
}


def _mock_transport(responses: dict[str, httpx.Response]) -> httpx.MockTransport:
    """Create a mock transport that maps URL paths to canned responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in responses:
            return responses[path]
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Tests — match the actual connector interface:
#   __init__(public_key, secret_key, host)
#   test_connection() -> bool
#   fetch_traces(since, limit) -> list[dict]
#   fetch_trace_detail(trace_id) -> dict
#   normalize_trace(raw) -> dict
#   sync(since) -> list[dict]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_connection_success():
    """test_connection returns True on 200."""
    connector = LangfuseConnector(
        public_key="pk-test", secret_key="sk-test", host="https://langfuse.example.com"
    )
    mock_resp = httpx.Response(200, json={"status": "ok"})

    with patch("connectors.langfuse.connector.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.get = AsyncMock(return_value=mock_resp)
        MockClient.return_value = instance

        result = await connector.test_connection()
        assert result is True


@pytest.mark.asyncio
async def test_test_connection_failure():
    """test_connection returns False on non-200 or exception."""
    connector = LangfuseConnector(
        public_key="pk-test", secret_key="sk-test", host="https://langfuse.example.com"
    )
    mock_resp = httpx.Response(401, json={"error": "unauthorized"})

    with patch("connectors.langfuse.connector.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.get = AsyncMock(return_value=mock_resp)
        MockClient.return_value = instance

        result = await connector.test_connection()
        assert result is False


@pytest.mark.asyncio
async def test_fetch_traces():
    """fetch_traces returns list of dicts from paginated API."""
    connector = LangfuseConnector(
        public_key="pk-test", secret_key="sk-test", host="https://langfuse.example.com"
    )
    page1_resp = httpx.Response(200, json={"data": [SAMPLE_TRACE_SUMMARY], "meta": {"totalItems": 1}})
    page2_resp = httpx.Response(200, json={"data": []})

    call_count = 0

    async def mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return page1_resp
        return page2_resp

    with patch("connectors.langfuse.connector.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.get = mock_get
        MockClient.return_value = instance

        since = datetime(2025, 1, 1, tzinfo=timezone.utc)
        traces = await connector.fetch_traces(since, limit=50)
        assert len(traces) == 1
        assert traces[0]["id"] == "trace-001"


@pytest.mark.asyncio
async def test_fetch_trace_detail():
    """fetch_trace_detail returns dict with observations merged in."""
    connector = LangfuseConnector(
        public_key="pk-test", secret_key="sk-test", host="https://langfuse.example.com"
    )
    trace_resp = httpx.Response(200, json={**SAMPLE_TRACE_SUMMARY, "latency": 2.5})
    obs_resp = httpx.Response(200, json={"data": [SAMPLE_OBSERVATION]})

    call_count = 0

    async def mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return trace_resp
        return obs_resp

    with patch("connectors.langfuse.connector.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.get = mock_get
        MockClient.return_value = instance

        detail = await connector.fetch_trace_detail("trace-001")
        assert detail["id"] == "trace-001"
        assert len(detail["observations"]) == 1


def test_normalize_trace_success():
    """normalize_trace returns a plain dict with expected fields."""
    connector = LangfuseConnector(
        public_key="pk-test", secret_key="sk-test", host="https://langfuse.example.com"
    )
    normalized = connector.normalize_trace(SAMPLE_TRACE_DETAIL)

    assert isinstance(normalized, dict)
    assert normalized["external_id"] == "trace-001"
    assert normalized["name"] == "customer-support-agent"
    assert normalized["status"] == "success"
    assert len(normalized["spans"]) == 1

    span = normalized["spans"][0]
    assert span["external_id"] == "obs-001"
    assert span["model"] == "gpt-4"
    assert span["tokens_in"] == 50
    assert span["duration_ms"] == 2000


def test_normalize_trace_with_error():
    """normalize_trace detects error observations and sets status to failure."""
    trace_with_error = {
        **SAMPLE_TRACE_DETAIL,
        "observations": [SAMPLE_OBSERVATION, SAMPLE_OBSERVATION_ERROR],
    }
    connector = LangfuseConnector(
        public_key="pk-test", secret_key="sk-test", host="https://langfuse.example.com"
    )
    normalized = connector.normalize_trace(trace_with_error)

    assert normalized["status"] == "failure"
    assert len(normalized["spans"]) == 2
    error_span = [s for s in normalized["spans"] if s["external_id"] == "obs-002"][0]
    assert error_span["status"] == "error"


def test_normalize_trace_no_observations():
    """normalize_trace with no observations returns success status."""
    trace_empty = {**SAMPLE_TRACE_DETAIL, "observations": []}
    connector = LangfuseConnector(
        public_key="pk-test", secret_key="sk-test", host="https://langfuse.example.com"
    )
    normalized = connector.normalize_trace(trace_empty)
    assert normalized["status"] == "success"
    assert normalized["spans"] == []


@pytest.mark.asyncio
async def test_sync_full_flow():
    """sync fetches traces, enriches with details, and returns list of dicts."""
    connector = LangfuseConnector(
        public_key="pk-test", secret_key="sk-test", host="https://langfuse.example.com"
    )

    # Mock fetch_traces and fetch_trace_detail
    connector.fetch_traces = AsyncMock(return_value=[SAMPLE_TRACE_SUMMARY])
    connector.fetch_trace_detail = AsyncMock(return_value=SAMPLE_TRACE_DETAIL)

    since = datetime(2025, 1, 1, tzinfo=timezone.utc)
    results = await connector.sync(since)

    assert len(results) == 1
    assert results[0]["id"] == "trace-001"
    assert "observations" in results[0]


@pytest.mark.asyncio
async def test_sync_skips_failed_detail_fetch():
    """sync continues when individual trace detail fetch fails."""
    connector = LangfuseConnector(
        public_key="pk-test", secret_key="sk-test", host="https://langfuse.example.com"
    )

    connector.fetch_traces = AsyncMock(return_value=[SAMPLE_TRACE_SUMMARY])
    connector.fetch_trace_detail = AsyncMock(side_effect=httpx.HTTPStatusError(
        "500", request=httpx.Request("GET", "http://test"), response=httpx.Response(500)
    ))

    since = datetime(2025, 1, 1, tzinfo=timezone.utc)
    results = await connector.sync(since)
    # On failure, sync appends the summary trace (without detail)
    assert len(results) == 1
    assert results[0]["id"] == "trace-001"
