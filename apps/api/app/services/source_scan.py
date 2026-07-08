"""Concurrent, rate-limit-resilient runner for the bulk source-completeness scan.

Runs :func:`app.services.source_chunks.scan_source` across many sources with a
bounded concurrency and exponential backoff, reusing the shared eval resilience
primitives (:func:`app.services.model_resilience.retry_async`). The retryable
predicate extends the eval one with the retrieval index's own throttling
(Azure AI Search answers 429/503 when a large scan outpaces its request budget).

Per-source failures never abort the scan: once retries are exhausted the item
collapses into an ``error`` outcome (the scan dead-letter set), mirroring the
eval executor's non-raising ``_call_target_api_resilient`` collapse.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.index_providers.base import BaseIndexProvider
from app.services.model_resilience import is_retryable, retry_async
from app.services.source_chunks import SourceChunkInput, SourceScanVerdict, scan_source


def scan_retryable(exc: BaseException) -> bool:
    """Retry the eval-transient failures plus the index's own request throttling."""
    if is_retryable(exc):
        return True
    # Azure AI Search (and most HTTP index backends) surface throttling as an
    # exception carrying a ``status_code``; 429 = too many requests, 503 = busy.
    # Matched by attribute so we don't hard-import the azure SDK here.
    status = getattr(exc, "status_code", None)
    return status in (429, 503)


@dataclass
class ScanItemOutcome:
    expectation_id: str
    verdict: SourceScanVerdict | None
    execution_status: str  # "ok" | "error"
    error: str | None = None


async def scan_sources(
    provider: BaseIndexProvider,
    sources: list[SourceChunkInput],
    *,
    concurrency: int,
    on_result: Callable[[ScanItemOutcome], Awaitable[None]],
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> None:
    """Scan every source concurrently; persist each via ``on_result``.

    ``on_result`` is awaited once per source (in completion order) with its
    outcome, so the caller can upsert it as it lands. ``on_progress(processed,
    failed)`` is awaited after each item with running totals, for a job's
    progress bar. Neither the gather nor a single item can raise out of here —
    item failures become ``error`` outcomes.
    """
    sem = asyncio.Semaphore(max(1, concurrency))
    lock = asyncio.Lock()
    processed = 0
    failed = 0

    async def run_one(source: SourceChunkInput) -> None:
        nonlocal processed, failed
        async with sem:
            try:
                verdict = await retry_async(
                    lambda: scan_source(provider, source), retryable=scan_retryable
                )
                outcome = ScanItemOutcome(source.id, verdict, "ok")
            except Exception as exc:  # noqa: BLE001 — collapse into the DLQ, never abort
                outcome = ScanItemOutcome(source.id, None, "error", str(exc)[:1000])
            await on_result(outcome)
            async with lock:
                processed += 1
                if outcome.execution_status == "error":
                    failed += 1
                snapshot = (processed, failed)
            if on_progress is not None:
                await on_progress(*snapshot)

    await asyncio.gather(*(run_one(s) for s in sources))
