"""LoopLM client + background trace sender."""

from __future__ import annotations

import atexit
import functools
import logging
import queue
import threading
from typing import Any, Callable, Optional

import httpx

from .tracing import Trace

logger = logging.getLogger("looplm")

_INGEST_PATH = "/api/v1/ingest/traces"


class _Sender:
    """Buffers trace dicts on a queue and POSTs them from a daemon thread.

    Delivery is best-effort: network errors are logged, never raised, so
    tracing can't break the host application.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        flush_interval: float = 2.0,
        max_batch: int = 50,
        timeout: float = 10.0,
    ):
        self._url = base_url.rstrip("/") + _INGEST_PATH
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._max_batch = max_batch
        self._flush_interval = flush_interval
        self._timeout = timeout
        self._stop = threading.Event()
        self._client = httpx.Client(timeout=timeout)
        self._thread = threading.Thread(target=self._run, name="looplm-sender", daemon=True)
        self._thread.start()
        atexit.register(self.shutdown)

    def enqueue(self, trace: dict) -> None:
        self._queue.put(trace)

    def _run(self) -> None:
        while not self._stop.is_set():
            batch = self._collect()
            if batch:
                self._post(batch)

    def _collect(self) -> list[dict]:
        batch: list[dict] = []
        try:
            batch.append(self._queue.get(timeout=self._flush_interval))
        except queue.Empty:
            return batch
        while len(batch) < self._max_batch:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def _drain(self) -> list[dict]:
        batch: list[dict] = []
        while True:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def _post(self, batch: list[dict]) -> None:
        try:
            resp = self._client.post(self._url, json={"traces": batch}, headers=self._headers)
            if resp.status_code >= 400:
                logger.warning("looplm ingest failed: HTTP %s %s", resp.status_code, resp.text[:300])
        except Exception as exc:  # noqa: BLE001 — never propagate to the host app
            logger.warning("looplm ingest error: %s", exc)

    def flush(self) -> None:
        """Synchronously send everything currently queued."""
        batch = self._drain()
        for i in range(0, len(batch), self._max_batch):
            self._post(batch[i : i + self._max_batch])

    def shutdown(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self._thread.join(timeout=self._timeout + self._flush_interval)
        self.flush()  # anything that arrived after the worker exited
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass


class LoopLM:
    """Entry point for first-party LoopLM tracing.

    >>> client = LoopLM(api_key="llm_sk_...", base_url="http://localhost:8000")
    >>> with client.trace("chat", user_id="u1") as t:
    ...     with t.span("llm", name="gpt", model="gpt-4o") as s:
    ...         s.set_tokens(input=120, output=80)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
        *,
        flush_interval: float = 2.0,
        max_batch: int = 50,
        timeout: float = 10.0,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self._sender = _Sender(
            api_key,
            base_url,
            flush_interval=flush_interval,
            max_batch=max_batch,
            timeout=timeout,
        )

    def trace(self, name: str, **kwargs: Any) -> Trace:
        """Start a trace. Use as a context manager."""
        return Trace(self._sender, name, **kwargs)

    def trace_fn(self, name: Optional[str] = None, **trace_kwargs: Any) -> Callable:
        """Decorator that wraps a function call in a trace."""

        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.trace(name or fn.__name__, **trace_kwargs):
                    return fn(*args, **kwargs)

            return wrapper

        return decorator

    def flush(self) -> None:
        """Block until all buffered traces have been sent."""
        self._sender.flush()

    def shutdown(self) -> None:
        """Flush and stop the background sender. Called automatically at exit."""
        self._sender.shutdown()
