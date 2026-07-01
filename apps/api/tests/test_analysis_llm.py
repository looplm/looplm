"""Tests for AnalysisLlmService's resilience (services/analysis_llm.py)."""

from __future__ import annotations

import httpx
import pytest
from openai import BadRequestError

from app.services.analysis_llm import AnalysisLlmService


def _bad_request(message: str) -> BadRequestError:
    req = httpx.Request("POST", "http://azure.test/chat")
    resp = httpx.Response(400, request=req)
    return BadRequestError(message, response=resp, body=None)


class _Usage:
    prompt_tokens = 1
    completion_tokens = 1
    total_tokens = 2
    prompt_tokens_details = None
    completion_tokens_details = None


class _Choice:
    def __init__(self, content: str):
        self.message = type("M", (), {"content": content})()


class _Response:
    def __init__(self, content: str):
        self.choices = [_Choice(content)]
        self.usage = _Usage()
        self.model = "gpt-test"


class _Completions:
    """Fake completions endpoint that fails on JSON mode, succeeds without it."""

    def __init__(self, fail_with_response_format: bool):
        self.fail_with_response_format = fail_with_response_format
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_with_response_format and "response_format" in kwargs:
            raise _bad_request("The requested operation is unsupported.")
        return _Response('{"queries": ["a"]}')


def _service_with(completions: _Completions) -> AnalysisLlmService:
    svc = AnalysisLlmService.__new__(AnalysisLlmService)
    svc.provider = "azure_openai"
    svc._model = "gpt-test"
    svc._client = type("C", (), {"chat": type("Ch", (), {"completions": completions})()})()
    return svc


@pytest.mark.asyncio
async def test_retries_without_response_format_when_json_mode_unsupported():
    completions = _Completions(fail_with_response_format=True)
    svc = _service_with(completions)

    content, _usage = await svc.tracked_chat_completion(
        messages=[{"role": "user", "content": "hi json"}],
        response_format={"type": "json_object"},
    )

    assert content == '{"queries": ["a"]}'
    # First call carried response_format and failed; retry dropped it and succeeded.
    assert len(completions.calls) == 2
    assert "response_format" in completions.calls[0]
    assert "response_format" not in completions.calls[1]


@pytest.mark.asyncio
async def test_persistent_bad_request_propagates_after_one_retry():
    # A 400 that survives stripping the optional params (e.g. context length) still propagates.
    class _AlwaysFails(_Completions):
        async def create(self, **kwargs):
            self.calls.append(kwargs)
            raise _bad_request("context_length_exceeded")

    completions = _AlwaysFails(fail_with_response_format=False)
    svc = _service_with(completions)

    with pytest.raises(BadRequestError):
        await svc.tracked_chat_completion(
            messages=[{"role": "user", "content": "x"}], temperature=0.0
        )
    # One retry (dropping the non-default temperature) then propagates.
    assert len(completions.calls) == 2
    assert "temperature" not in completions.calls[1]


@pytest.mark.asyncio
async def test_no_retry_when_nothing_to_strip():
    # temperature=1 and no response_format: nothing to strip, so a 400 propagates immediately.
    class _AlwaysFails(_Completions):
        async def create(self, **kwargs):
            self.calls.append(kwargs)
            raise _bad_request("content_filter")

    completions = _AlwaysFails(fail_with_response_format=False)
    svc = _service_with(completions)

    with pytest.raises(BadRequestError):
        await svc.tracked_chat_completion(
            messages=[{"role": "user", "content": "x"}], temperature=1
        )
    assert len(completions.calls) == 1
