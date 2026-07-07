"""Tests for outbound-call resilience: retry classification, backoff cap, and the
resilient target wrapper's degrade/error/soft-failure outcomes."""

from __future__ import annotations

import httpx
import pytest
from openai import RateLimitError

from app.services import eval_executor_helpers as helpers
from app.services.model_resilience import (
    DEGRADED_RETRIEVAL_MODE,
    DegradedRetrievalError,
    is_retryable,
    retry_async,
)


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://example.test")
    response = httpx.Response(429, request=request)
    return RateLimitError("throttled", response=response, body=None)


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.test")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


# --- is_retryable ---

def test_is_retryable_true_for_degrade_and_transient():
    assert is_retryable(DegradedRetrievalError(DEGRADED_RETRIEVAL_MODE))
    assert is_retryable(_rate_limit_error())
    assert is_retryable(httpx.ReadTimeout("slow"))
    assert is_retryable(httpx.ConnectError("refused"))
    assert is_retryable(_status_error(429))
    assert is_retryable(_status_error(503))


def test_is_retryable_false_for_client_errors_and_generic():
    assert not is_retryable(_status_error(400))
    assert not is_retryable(_status_error(404))
    assert not is_retryable(ValueError("nope"))


# --- retry_async ---

@pytest.mark.asyncio
async def test_retry_async_retries_then_succeeds(monkeypatch):
    import app.services.model_resilience as mr

    slept: list[float] = []

    async def _fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(mr.asyncio, "sleep", _fake_sleep)

    calls = {"n": 0}
    attempts_seen: list[int] = []

    async def _flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _rate_limit_error()
        return "ok"

    async def _on_retry(attempt, delay, exc):
        attempts_seen.append(attempt)

    result = await retry_async(_flaky, base=1.0, jitter=0.0, max_delay=30.0, on_retry=_on_retry)
    assert result == "ok"
    assert calls["n"] == 3
    assert attempts_seen == [1, 2]
    # Exponential base with no jitter: 1s then 2s.
    assert slept == [1.0, 2.0]


@pytest.mark.asyncio
async def test_retry_async_gives_up_on_non_retryable():
    calls = {"n": 0}

    async def _bad():
        calls["n"] += 1
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await retry_async(_bad, max_attempts=5)
    assert calls["n"] == 1  # no retries for non-retryable


@pytest.mark.asyncio
async def test_retry_async_caps_backoff(monkeypatch):
    import app.services.model_resilience as mr
    slept: list[float] = []

    async def _fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(mr.asyncio, "sleep", _fake_sleep)

    async def _always_fail():
        raise _rate_limit_error()

    with pytest.raises(RateLimitError):
        await retry_async(_always_fail, max_attempts=6, base=1.0, jitter=0.0, max_delay=4.0)
    # base*2**(n) would be 1,2,4,8,16; capped at 4.
    assert slept == [1.0, 2.0, 4.0, 4.0, 4.0]


# --- _call_target_api_resilient ---

def _degraded_raw() -> str:
    return '{"answer": "kw", "retrievalDiagnostics": {"retrievalMode": "keyword-fallback"}}'


def _ok_raw() -> str:
    return '{"answer": "vec", "retrievalDiagnostics": {"retrievalMode": "hybrid"}}'


@pytest.mark.asyncio
async def test_resilient_ok_passthrough(monkeypatch):
    async def _fake_call(*a, **k):
        return ("vec", _ok_raw(), 12)

    monkeypatch.setattr(helpers, "_call_target_api", _fake_call)
    outcome = await helpers._call_target_api_resilient("client", "ep", {}, "answer", {}, "q")
    assert outcome.status == "ok"
    assert outcome.output_text == "vec"
    assert outcome.retrieval_mode == "hybrid"
    assert outcome.attempts == 1


@pytest.mark.asyncio
async def test_resilient_degrade_exhausts_to_soft_failure(monkeypatch):
    import app.services.model_resilience as mr

    async def _no_sleep(d):
        return None

    monkeypatch.setattr(mr.asyncio, "sleep", _no_sleep)
    calls = {"n": 0}

    async def _fake_call(*a, **k):
        calls["n"] += 1
        return ("kw", _degraded_raw(), 5)

    monkeypatch.setattr(helpers, "_call_target_api", _fake_call)
    outcome = await helpers._call_target_api_resilient(
        "client", "ep", {}, "answer", {}, "q", max_attempts=None
    )
    # Retried up to the default budget, then kept the degraded response as a soft failure.
    assert outcome.status == "degraded"
    assert outcome.retrieval_mode == DEGRADED_RETRIEVAL_MODE
    assert outcome.output_text == "kw"  # payload preserved, not lost
    assert calls["n"] > 1


@pytest.mark.asyncio
async def test_resilient_no_retry_when_stateful(monkeypatch):
    calls = {"n": 0}

    async def _fake_call(*a, **k):
        calls["n"] += 1
        return ("kw", _degraded_raw(), 5)

    monkeypatch.setattr(helpers, "_call_target_api", _fake_call)
    outcome = await helpers._call_target_api_resilient(
        "client", "ep", {}, "answer", {}, "q", allow_retry=False
    )
    assert outcome.status == "degraded"
    assert calls["n"] == 1  # stateful call runs exactly once, no thread pollution


@pytest.mark.asyncio
async def test_resilient_hard_error_collapses_to_error(monkeypatch):
    async def _fake_call(*a, **k):
        raise _status_error(400)  # non-retryable

    monkeypatch.setattr(helpers, "_call_target_api", _fake_call)
    outcome = await helpers._call_target_api_resilient("client", "ep", {}, "answer", {}, "q")
    assert outcome.status == "error"
    assert outcome.output_text is None
    assert outcome.error


# --- execution_status_of ---

def test_execution_status_of_defaults_ok():
    assert helpers.execution_status_of(None) == "ok"
    assert helpers.execution_status_of({}) == "ok"
    assert helpers.execution_status_of({"execution": {"status": "degraded"}}) == "degraded"
    assert helpers.execution_status_of({"execution": {"status": "error"}}) == "error"
