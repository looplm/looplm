"""Shared resilience primitives for outbound model calls (eval target + embeddings).

Two failure classes need bounding, and they fail in opposite ways:

* The eval **target** RAG endpoint fails *silently* — it returns HTTP 200 with
  ``retrievalDiagnostics.retrievalMode == "keyword-fallback"`` when its shared
  embeddings deployment throttled and it degraded to keyword-only retrieval. That
  response is not representative of prod, so callers raise :class:`DegradedRetrievalError`
  to make it retryable (there is no exception to catch otherwise).
* LoopLM's **own** model calls (query embeddings, LLM judges) fail with real
  ``429``/timeout/5xx. The OpenAI SDK retries those internally; :func:`retry_async`
  covers the httpx target call and anything the SDK does not.

:data:`GLOBAL_TARGET_SEM` bounds *total* concurrent target calls across every eval
job/session in the process. ``settings.eval_max_concurrency`` already caps a single
run; this caps the sum, so several evals running in parallel can't stack their
per-run concurrency into the target embeddings throttle.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# The exact retrievalMode the target reports when it degraded to keyword-only
# retrieval (embeddings throttled). Kept in sync with the value the run summary
# flags in retrieval_metrics_aggregate.
DEGRADED_RETRIEVAL_MODE = "keyword-fallback"


class DegradedRetrievalError(Exception):
    """The target returned a degraded (keyword-only) retrieval response.

    Raised by callers so :func:`retry_async` re-attempts under backoff. Carries the
    last payload so a caller can fall back to it once retries are exhausted, rather
    than losing the response entirely.
    """

    def __init__(self, mode: str, payload: object | None = None) -> None:
        super().__init__(f"target degraded to {mode!r} retrieval")
        self.mode = mode
        self.payload = payload


# Process-wide ceiling on concurrent target calls, shared across all eval jobs.
GLOBAL_TARGET_SEM = asyncio.Semaphore(settings.eval_global_max_concurrency)


def is_retryable(exc: BaseException) -> bool:
    """True for transient failures worth re-attempting under backoff."""
    if isinstance(exc, DegradedRetrievalError):
        return True
    if isinstance(exc, (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)):
        return True
    # httpx.TransportError covers timeouts, connect/read/write and protocol errors.
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or 500 <= status < 600
    return False


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int | None = None,
    base: float | None = None,
    jitter: float | None = None,
    retryable: Callable[[BaseException], bool] = is_retryable,
    on_retry: Callable[[int, float, BaseException], Awaitable[None]] | None = None,
) -> T:
    """Call ``fn`` with exponential backoff + jitter on retryable failures.

    ``max_attempts`` is the total number of tries (first attempt + retries); it
    defaults to ``settings.eval_target_max_retries + 1``. On a non-retryable
    exception, or once attempts are exhausted, the last exception propagates.
    ``on_retry(attempt, delay, exc)`` is awaited before each backoff sleep, so
    callers can surface progress and count attempts.
    """
    max_attempts = max_attempts if max_attempts is not None else settings.eval_target_max_retries + 1
    base = base if base is not None else settings.eval_backoff_base_seconds
    jitter = jitter if jitter is not None else settings.eval_backoff_jitter_seconds

    attempt = 0
    while True:
        attempt += 1
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 — classified by ``retryable``
            if attempt >= max_attempts or not retryable(exc):
                raise
            delay = base * (2 ** (attempt - 1)) + random.uniform(0, jitter)
            if on_retry is not None:
                await on_retry(attempt, delay, exc)
            logger.info(
                "Retryable failure (attempt %d/%d), backing off %.2fs: %s",
                attempt,
                max_attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
