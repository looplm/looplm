"""Shared persistence for normalized traces.

This is the single code path that turns a *normalized trace dict* (the shape
produced by connector ``normalize_trace`` and by the first-party ingest
endpoint) into ``Trace``/``Span`` rows. Both the pull-based sync
(``sync_service.run_sync``) and the push-based ingest endpoint call
``persist_normalized_trace`` so the two share one tested implementation.

Normalized trace dict shape (all keys optional unless noted):

    {
      "external_id": str,            # REQUIRED, unique per integration
      "name": str, "input": dict, "output": dict, "metadata": dict,
      "start_time": datetime,        # REQUIRED for new traces (NOT NULL)
      "end_time": datetime, "duration_ms": int,
      "status": str, "error_message": str,
      "thread_id": str, "user_id": str, "run_type": str,
      "spans": [ {..span.., "parent_external_id": str} ],
      "child_traces": [ {..trace.., "parent_external_id": str} ],
    }
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Span, Trace

PersistStatus = Literal["created", "updated", "skipped"]


def strip_null_bytes(obj: Any) -> Any:
    """Recursively strip PostgreSQL-incompatible \\x00 bytes from strings."""
    if isinstance(obj, str):
        return obj.replace("\x00", "")
    if isinstance(obj, dict):
        return {k: strip_null_bytes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_null_bytes(item) for item in obj]
    return obj


async def _insert_spans(db: AsyncSession, trace_id: UUID, spans_list: list[dict[str, Any]]) -> None:
    """Insert spans for a trace and resolve parent_span_id from external refs."""
    ext_to_span_id: dict[str, UUID] = {}
    for span_data in spans_list:
        span = Span(
            trace_id=trace_id,
            external_id=span_data.get("external_id"),
            name=span_data.get("name"),
            type=span_data.get("type"),
            input=span_data.get("input"),
            output=span_data.get("output"),
            model=span_data.get("model"),
            tokens_in=span_data.get("tokens_in"),
            tokens_out=span_data.get("tokens_out"),
            duration_ms=span_data.get("duration_ms"),
            status=span_data.get("status"),
            error_message=span_data.get("error_message"),
        )
        db.add(span)
        await db.flush()
        if span_data.get("external_id"):
            ext_to_span_id[span_data["external_id"]] = span.id

    # Second pass: resolve parent_span_id now that every external_id is mapped.
    for span_data in spans_list:
        parent_ext = span_data.get("parent_external_id")
        if (
            parent_ext
            and parent_ext in ext_to_span_id
            and span_data.get("external_id") in ext_to_span_id
        ):
            await db.execute(
                update(Span)
                .where(Span.id == ext_to_span_id[span_data["external_id"]])
                .values(parent_span_id=ext_to_span_id[parent_ext])
            )


async def _insert_child_traces(
    db: AsyncSession, integration_id: UUID, root_trace: Trace, normalized: dict[str, Any]
) -> None:
    """Insert child runs as Trace rows with parent/root hierarchy.

    Runs for both new and existing root traces so re-syncs backfill children.
    """
    child_traces_data = normalized.get("child_traces", [])
    if not child_traces_data:
        return

    # Map from external_id to LoopLM UUID, seeded with the root.
    ext_id_to_uuid: dict[str, UUID] = {normalized["external_id"]: root_trace.id}
    # Sort by start_time so parents are processed before their children.
    child_traces_data.sort(
        key=lambda c: c.get("start_time") or datetime.min.replace(tzinfo=timezone.utc)
    )

    for child_data in child_traces_data:
        child_ext_id = child_data["external_id"]
        existing_child = await db.execute(
            select(Trace).where(
                Trace.integration_id == integration_id,
                Trace.external_id == child_ext_id,
            )
        )
        existing_child_trace = existing_child.scalar_one_or_none()
        if existing_child_trace:
            ext_id_to_uuid[child_ext_id] = existing_child_trace.id
            continue

        parent_ext_id = child_data.get("parent_external_id")
        parent_trace_id = (
            ext_id_to_uuid.get(parent_ext_id, root_trace.id) if parent_ext_id else root_trace.id
        )

        child_trace = Trace(
            integration_id=integration_id,
            external_id=child_ext_id,
            name=child_data.get("name"),
            input=child_data.get("input"),
            output=child_data.get("output"),
            trace_metadata=child_data.get("metadata", {}),
            start_time=child_data.get("start_time") or normalized["start_time"],
            end_time=child_data.get("end_time"),
            duration_ms=child_data.get("duration_ms"),
            status=child_data.get("status"),
            error_message=child_data.get("error_message"),
            run_type=child_data.get("run_type"),
            parent_trace_id=parent_trace_id,
            root_trace_id=root_trace.id,
            thread_id=normalized.get("thread_id"),
            user_id=normalized.get("user_id"),
        )
        db.add(child_trace)
        await db.flush()
        ext_id_to_uuid[child_ext_id] = child_trace.id


async def persist_normalized_trace(
    db: AsyncSession,
    integration_id: UUID,
    normalized: dict[str, Any],
    raw_data: dict[str, Any] | None = None,
    *,
    update_existing: bool = False,
) -> tuple[UUID, PersistStatus]:
    """Persist one normalized trace (root + spans + child traces).

    Idempotent on ``(integration_id, external_id)``:
      - new trace            → inserted, status "created"
      - existing + update    → root fields + spans replaced, status "updated"
      - existing, no update  → left as-is, status "skipped" (safe SDK retry)

    Child traces are (re)backfilled in every case. Returns the *root* trace id
    and the status. Does not commit — the caller owns the transaction.
    """
    normalized = strip_null_bytes(normalized)
    raw_data = strip_null_bytes(raw_data)
    result = await db.execute(
        select(Trace).where(
            Trace.integration_id == integration_id,
            Trace.external_id == normalized["external_id"],
        )
    )
    existing_trace = result.scalar_one_or_none()

    if existing_trace is None:
        trace = Trace(
            integration_id=integration_id,
            external_id=normalized["external_id"],
            name=normalized.get("name"),
            input=normalized.get("input"),
            output=normalized.get("output"),
            trace_metadata=normalized.get("metadata", {}),
            start_time=normalized["start_time"],
            end_time=normalized.get("end_time"),
            duration_ms=normalized.get("duration_ms"),
            status=normalized.get("status"),
            error_message=normalized.get("error_message"),
            raw_data=raw_data,
            thread_id=normalized.get("thread_id"),
            user_id=normalized.get("user_id"),
            run_type=normalized.get("run_type"),
        )
        db.add(trace)
        await db.flush()
        await _insert_spans(db, trace.id, normalized.get("spans", []))
        status: PersistStatus = "created"
    else:
        trace = existing_trace
        if update_existing:
            trace.name = normalized.get("name")
            trace.input = normalized.get("input")
            trace.output = normalized.get("output")
            trace.trace_metadata = normalized.get("metadata", {})
            trace.end_time = normalized.get("end_time")
            trace.duration_ms = normalized.get("duration_ms")
            trace.status = normalized.get("status")
            trace.error_message = normalized.get("error_message")
            trace.raw_data = raw_data
            trace.thread_id = normalized.get("thread_id")
            trace.user_id = normalized.get("user_id")

            await db.execute(delete(Span).where(Span.trace_id == trace.id))
            await db.flush()
            await _insert_spans(db, trace.id, normalized.get("spans", []))
            status = "updated"
        else:
            status = "skipped"

    await _insert_child_traces(db, integration_id, trace, normalized)
    return trace.id, status
