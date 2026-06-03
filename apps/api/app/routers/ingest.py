"""First-party tracing ingest endpoint (push-based SDK → LoopLM).

Apps authenticate with an ingest key (machine auth, no user JWT) and POST whole
traces — root + spans — which are persisted through the same
``persist_normalized_trace`` path used by the pull-based connectors. Ingested
traces are therefore indistinguishable from synced ones to every read surface.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_ingest_context
from app.config import settings
from app.db import get_db
from app.models.integrations import Integration
from app.models.project import Project
from app.schemas.ingest import IngestRequest, IngestResponse, IngestSpan, IngestTrace
from app.services.trace_persistence import persist_normalized_trace

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])


def _derive_duration_ms(
    duration_ms: int | None, start_time: datetime | None, end_time: datetime | None
) -> int | None:
    if duration_ms is not None:
        return duration_ms
    if start_time and end_time:
        return max(0, int((end_time - start_time).total_seconds() * 1000))
    return None


def _span_to_dict(span: IngestSpan) -> dict:
    return {
        "external_id": span.external_id or str(uuid4()),
        "name": span.name,
        "type": span.type,
        "input": span.input,
        "output": span.output,
        "model": span.model,
        "tokens_in": span.input_tokens,
        "tokens_out": span.output_tokens,
        "duration_ms": _derive_duration_ms(span.duration_ms, span.start_time, span.end_time),
        "status": span.status,
        "error_message": span.error_message,
        "parent_external_id": span.parent_external_id,
    }


def _trace_to_normalized(trace: IngestTrace) -> dict:
    start_time = trace.start_time or datetime.now(timezone.utc)
    return {
        "external_id": trace.external_id or str(uuid4()),
        "name": trace.name,
        "input": trace.input,
        "output": trace.output,
        "metadata": trace.metadata,
        "start_time": start_time,
        "end_time": trace.end_time,
        "duration_ms": _derive_duration_ms(trace.duration_ms, start_time, trace.end_time),
        "status": trace.status,
        "error_message": trace.error_message,
        "thread_id": trace.thread_id,
        "user_id": trace.user_id,
        "run_type": trace.run_type,
        "spans": [_span_to_dict(s) for s in trace.spans],
    }


@router.post("/traces", response_model=IngestResponse, status_code=201)
async def ingest_traces(
    body: IngestRequest,
    ctx: tuple[Integration, Project] = Depends(get_ingest_context),
    db: AsyncSession = Depends(get_db),
):
    """Persist a batch of pushed traces. Idempotent on (integration, external_id)."""
    if not settings.ingest_enabled:
        raise HTTPException(status_code=503, detail="Trace ingest is disabled")

    integration, _project = ctx

    if len(body.traces) > settings.ingest_max_batch:
        raise HTTPException(
            status_code=413,
            detail=f"Batch too large: {len(body.traces)} traces (max {settings.ingest_max_batch})",
        )

    trace_ids: list[str] = []
    for trace in body.traces:
        if len(trace.spans) > settings.ingest_max_spans_per_trace:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Trace has too many spans: {len(trace.spans)} "
                    f"(max {settings.ingest_max_spans_per_trace})"
                ),
            )
        normalized = _trace_to_normalized(trace)
        root_id, _status = await persist_normalized_trace(db, integration.id, normalized)
        trace_ids.append(str(root_id))

    # Push liveness — shares the request session, committed by get_db on success.
    integration.last_received_at = datetime.now(timezone.utc)

    return IngestResponse(accepted=len(trace_ids), trace_ids=trace_ids)
