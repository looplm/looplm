"""Trace and Span context managers.

A ``Trace`` buffers its spans in-process and, on exit, hands the *whole* trace
to the sender for delivery. Spans nest via a per-trace stack so
``parent_external_id`` is resolved automatically.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


class Span:
    """A unit of work within a trace (LLM call, tool call, chain step, ...)."""

    def __init__(
        self,
        trace: "Trace",
        *,
        type: str = "chain",
        name: Optional[str] = None,
        model: Optional[str] = None,
        input: Any = None,
        external_id: Optional[str] = None,
    ):
        self._trace = trace
        self.external_id = external_id or str(uuid.uuid4())
        self.type = type
        self.name = name
        self.model = model
        self.input = input
        self.output: Any = None
        self.input_tokens: Optional[int] = None
        self.output_tokens: Optional[int] = None
        self.status = "success"
        self.error_message: Optional[str] = None
        self.parent_external_id: Optional[str] = None
        self._start: Optional[datetime] = None
        self._end: Optional[datetime] = None

    def __enter__(self) -> "Span":
        self._start = _now()
        stack = self._trace._stack
        self.parent_external_id = stack[-1].external_id if stack else None
        stack.append(self)
        return self

    def set_tokens(self, input: Optional[int] = None, output: Optional[int] = None) -> "Span":
        if input is not None:
            self.input_tokens = input
        if output is not None:
            self.output_tokens = output
        return self

    def set_input(self, value: Any) -> "Span":
        self.input = value
        return self

    def set_output(self, value: Any) -> "Span":
        self.output = value
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._end = _now()
        stack = self._trace._stack
        if stack and stack[-1] is self:
            stack.pop()
        if exc_type is not None:
            self.status = "error"
            self.error_message = f"{exc_type.__name__}: {exc}"
        self._trace._spans.append(self._to_dict())
        return False  # never swallow exceptions

    def _to_dict(self) -> dict:
        duration_ms = None
        if self._start and self._end:
            duration_ms = max(0, int((self._end - self._start).total_seconds() * 1000))
        return {
            "external_id": self.external_id,
            "name": self.name,
            "type": self.type,
            "input": self.input,
            "output": self.output,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_ms": duration_ms,
            "status": self.status,
            "error_message": self.error_message,
            "parent_external_id": self.parent_external_id,
        }


class Trace:
    """A single end-to-end execution (one request / agent run)."""

    def __init__(
        self,
        sender,
        name: str,
        *,
        input: Any = None,
        metadata: Optional[dict] = None,
        user_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        run_type: Optional[str] = None,
        external_id: Optional[str] = None,
    ):
        self._sender = sender
        self.external_id = external_id or str(uuid.uuid4())
        self.name = name
        self.input = input
        self.output: Any = None
        self.metadata = dict(metadata or {})
        self.user_id = user_id
        self.thread_id = thread_id
        self.run_type = run_type
        self.status = "success"
        self.error_message: Optional[str] = None
        self._start: Optional[datetime] = None
        self._end: Optional[datetime] = None
        self._spans: list[dict] = []
        self._stack: list[Span] = []

    def __enter__(self) -> "Trace":
        self._start = _now()
        return self

    def span(
        self,
        type: str = "chain",
        *,
        name: Optional[str] = None,
        model: Optional[str] = None,
        input: Any = None,
    ) -> Span:
        """Open a child span. Nest these to build a span tree."""
        return Span(self, type=type, name=name, model=model, input=input)

    def set_output(self, value: Any) -> "Trace":
        self.output = value
        return self

    def set_metadata(self, **kwargs: Any) -> "Trace":
        self.metadata.update(kwargs)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._end = _now()
        if exc_type is not None:
            self.status = "failure"
            self.error_message = f"{exc_type.__name__}: {exc}"
        self._sender.enqueue(self._to_dict())
        return False

    def _to_dict(self) -> dict:
        return {
            "external_id": self.external_id,
            "name": self.name,
            "input": self.input,
            "output": self.output,
            "metadata": self.metadata,
            "start_time": _iso(self._start),
            "end_time": _iso(self._end),
            "status": self.status,
            "error_message": self.error_message,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "run_type": self.run_type,
            "spans": self._spans,
        }
