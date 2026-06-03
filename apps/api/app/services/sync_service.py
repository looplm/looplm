"""Sync service — orchestrates pulling traces from connectors."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.encryption import decrypt_api_key
from app.models.models import FeedbackScore, Integration, IntegrationType, Span, SyncStatus, Trace
from connectors.base import SyncProgress

logger = logging.getLogger(__name__)


def _format_sync_error(e: Exception) -> str:
    """Build a human-readable error message, including HTTP status/body when available."""
    import httpx

    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        try:
            body = e.response.json()
            detail = body.get("message") or body.get("error") or body.get("detail") or ""
        except Exception:
            detail = e.response.text[:500] if e.response.text else ""
        return f"HTTP {status}: {detail}".strip() if detail else f"HTTP {status}"

    # Check for response attribute on other exception types (e.g. httpx auth errors)
    response = getattr(e, "response", None)
    if response is not None and hasattr(response, "status_code"):
        status = response.status_code
        try:
            detail = response.json().get("message") or response.text[:500]
        except Exception:
            detail = getattr(response, "text", "")[:500]
        return f"HTTP {status}: {detail}".strip() if detail else f"HTTP {status}"

    msg = str(e)
    if msg:
        return msg

    # Fallback: use the exception class name for exceptions with empty str()
    class_name = type(e).__name__
    return f"{class_name} — check your integration credentials and base URL"


def _strip_null_bytes(obj):
    """Recursively strip PostgreSQL-incompatible \\x00 bytes from strings."""
    if isinstance(obj, str):
        return obj.replace("\x00", "")
    if isinstance(obj, dict):
        return {k: _strip_null_bytes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_null_bytes(item) for item in obj]
    return obj


async def run_sync(integration_id: UUID, db: AsyncSession, *, since_override: datetime | None = None, update_existing: bool = False) -> int:
    """Run a sync for the given integration. Returns number of new traces."""
    result = await db.execute(select(Integration).where(Integration.id == integration_id))
    integration = result.scalar_one_or_none()
    if not integration:
        raise ValueError(f"Integration {integration_id} not found")

    try:
        connector = _get_connector(integration)
        since = since_override or integration.last_synced_at or datetime(2020, 1, 1, tzinfo=timezone.utc)

        integration.sync_since = since
        integration.sync_phase = "fetching_traces"
        integration.sync_message = f"Connecting to {integration.type.value}…"
        await db.commit()

        async def on_progress(p: SyncProgress) -> None:
            integration.sync_phase = p.phase
            integration.sync_message = p.message[:255]
            if p.total is not None:
                integration.sync_progress_total = p.total
            if p.current is not None:
                integration.sync_progress_current = p.current
            await db.commit()

        raw_traces = await connector.sync(since, on_progress=on_progress, limit=settings.sync_max_traces)

        integration.sync_phase = "processing_traces"
        integration.sync_message = f"Storing {len(raw_traces)} traces"
        integration.sync_progress_total = len(raw_traces)
        integration.sync_progress_current = 0
        await db.commit()

        count = 0
        processed = 0
        for raw in raw_traces:
            normalized = _strip_null_bytes(connector.normalize_trace(raw))
            raw = _strip_null_bytes(raw)
            # Check for duplicate root trace
            existing = await db.execute(
                select(Trace).where(
                    Trace.integration_id == integration.id,
                    Trace.external_id == normalized["external_id"],
                )
            )
            existing_trace = existing.scalar_one_or_none()
            is_new = existing_trace is None

            if is_new:
                trace = Trace(
                    integration_id=integration.id,
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
                    raw_data=raw,
                    thread_id=normalized.get("thread_id"),
                    user_id=normalized.get("user_id"),
                    run_type=normalized.get("run_type"),
                )
                db.add(trace)
                await db.flush()

                # Store spans (backward compat)
                ext_to_span_id: dict[str, "UUID"] = {}
                spans_list = normalized.get("spans", [])
                for span_data in spans_list:
                    span = Span(
                        trace_id=trace.id,
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

                # Resolve parent_span_id from external parent references
                for span_data in spans_list:
                    parent_ext = span_data.get("parent_external_id")
                    if parent_ext and parent_ext in ext_to_span_id and span_data.get("external_id") in ext_to_span_id:
                        await db.execute(
                            update(Span)
                            .where(Span.id == ext_to_span_id[span_data["external_id"]])
                            .values(parent_span_id=ext_to_span_id[parent_ext])
                        )

                count += 1
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
                    trace.raw_data = raw
                    trace.thread_id = normalized.get("thread_id")
                    trace.user_id = normalized.get("user_id")

                    # Delete existing spans and re-create them
                    await db.execute(delete(Span).where(Span.trace_id == trace.id))
                    await db.flush()

                    ext_to_span_id_upd: dict[str, UUID] = {}
                    spans_list_upd = normalized.get("spans", [])
                    for span_data in spans_list_upd:
                        span = Span(
                            trace_id=trace.id,
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
                            ext_to_span_id_upd[span_data["external_id"]] = span.id

                    for span_data in spans_list_upd:
                        parent_ext = span_data.get("parent_external_id")
                        if parent_ext and parent_ext in ext_to_span_id_upd and span_data.get("external_id") in ext_to_span_id_upd:
                            await db.execute(
                                update(Span)
                                .where(Span.id == ext_to_span_id_upd[span_data["external_id"]])
                                .values(parent_span_id=ext_to_span_id_upd[parent_ext])
                            )

                    count += 1

            # Store child runs as Trace records with hierarchy
            # (runs for both new and existing root traces so re-syncs backfill children)
            child_traces_data = normalized.get("child_traces", [])
            if child_traces_data:
                # Map from LangSmith external_id to LoopLM UUID
                ext_id_to_uuid: dict[str, UUID] = {normalized["external_id"]: trace.id}

                # Sort children by start_time so parents are processed before children
                child_traces_data.sort(key=lambda c: c.get("start_time") or datetime.min.replace(tzinfo=timezone.utc))

                for child_data in child_traces_data:
                    child_ext_id = child_data["external_id"]
                    # Skip if already exists
                    existing_child = await db.execute(
                        select(Trace).where(
                            Trace.integration_id == integration.id,
                            Trace.external_id == child_ext_id,
                        )
                    )
                    existing_child_trace = existing_child.scalar_one_or_none()
                    if existing_child_trace:
                        ext_id_to_uuid[child_ext_id] = existing_child_trace.id
                        continue

                    # Resolve parent_trace_id
                    parent_ext_id = child_data.get("parent_external_id")
                    parent_trace_id = ext_id_to_uuid.get(parent_ext_id, trace.id) if parent_ext_id else trace.id

                    child_trace = Trace(
                        integration_id=integration.id,
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
                        root_trace_id=trace.id,
                        thread_id=normalized.get("thread_id"),
                        user_id=normalized.get("user_id"),
                    )
                    db.add(child_trace)
                    await db.flush()
                    ext_id_to_uuid[child_ext_id] = child_trace.id
            processed += 1
            integration.sync_progress_current = processed
            await db.commit()

        # Sync scores (feedback + grader scores) for Langfuse integrations
        score_count = 0
        if integration.type == IntegrationType.langfuse and hasattr(connector, "fetch_scores"):
            try:
                score_count = await _sync_scores(connector, integration, db, on_progress=on_progress)
            except Exception as e:
                logger.warning("Score sync failed for integration %s: %s", integration_id, e)

        integration.sync_status = SyncStatus.idle
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_sync_error = None
        integration.sync_progress_current = None
        integration.sync_progress_total = None
        integration.sync_started_at = None
        integration.sync_phase = None
        integration.sync_message = None
        integration.sync_since = None
        await db.commit()

        logger.info(
            "Synced %d new traces and %d scores for integration %s",
            count, score_count, integration_id,
        )
        return count

    except Exception as e:
        error_msg = _format_sync_error(e)
        logger.error("Sync failed for integration %s: %s", integration_id, error_msg)
        await db.rollback()
        # Re-fetch after rollback to avoid expired ORM state
        result = await db.execute(
            select(Integration).where(Integration.id == integration_id)
        )
        integration = result.scalar_one_or_none()
        if integration:
            integration.sync_status = SyncStatus.error
            integration.last_sync_error = error_msg
            await db.commit()
        raise


async def _sync_scores(connector, integration: Integration, db: AsyncSession, *, on_progress=None) -> int:
    """Sync scores from Langfuse into feedback_scores table."""
    # Backfill trace_id on scores that were synced before their trace existed
    trace_subq = (
        select(Trace.id)
        .where(
            Trace.integration_id == integration.id,
            Trace.external_id == FeedbackScore.external_trace_id,
        )
        .correlate(FeedbackScore)
        .scalar_subquery()
    )
    backfill = (
        update(FeedbackScore)
        .where(
            FeedbackScore.integration_id == integration.id,
            FeedbackScore.trace_id.is_(None),
            FeedbackScore.external_trace_id.isnot(None),
        )
        .values(trace_id=trace_subq)
    )
    result = await db.execute(backfill)
    if result.rowcount:
        logger.info("Backfilled trace_id on %d scores for integration %s", result.rowcount, integration.id)

    since = integration.last_synced_at or datetime(2020, 1, 1, tzinfo=timezone.utc)
    raw_scores = await connector.fetch_scores(since, on_progress=on_progress)
    logger.info("Fetched %d raw scores for integration %s", len(raw_scores), integration.id)
    if on_progress is not None and raw_scores:
        await on_progress(SyncProgress(
            phase="processing_scores",
            message=f"Storing {len(raw_scores)} feedback scores",
            current=0,
            total=len(raw_scores),
        ))

    count = 0
    for raw in raw_scores:
        normalized = connector.normalize_score(raw)
        external_id = normalized["external_id"]
        if not external_id:
            continue

        # Check for duplicate
        existing = await db.execute(
            select(FeedbackScore).where(
                FeedbackScore.integration_id == integration.id,
                FeedbackScore.external_id == external_id,
            )
        )
        existing_score = existing.scalar_one_or_none()

        # Resolve internal trace_id from external_trace_id
        external_trace_id = normalized["trace_id"]
        trace_id = None
        if external_trace_id:
            trace_result = await db.execute(
                select(Trace.id).where(
                    Trace.integration_id == integration.id,
                    Trace.external_id == external_trace_id,
                )
            )
            trace_id = trace_result.scalar_one_or_none()

        # Backfill trace_id on existing scores that were synced before their trace
        if existing_score:
            if existing_score.trace_id is None and trace_id is not None:
                existing_score.trace_id = trace_id
                count += 1
            continue

        score = FeedbackScore(
            integration_id=integration.id,
            trace_id=trace_id,
            external_id=external_id,
            external_trace_id=external_trace_id,
            score_name=normalized["name"],
            value=normalized["value"],
            data_type=normalized["data_type"],
            comment=normalized.get("comment"),
            scored_at=normalized.get("scored_at"),
        )
        db.add(score)
        count += 1

    if count > 0:
        await db.flush()
    return count


def _get_connector(integration: Integration):
    """Factory to get the right connector for an integration."""
    from connectors.langfuse.connector import LangfuseConnector
    from connectors.langsmith.connector import LangSmithConnector

    api_key = decrypt_api_key(integration.api_key)

    if integration.type == IntegrationType.langfuse:
        config = integration.config or {}
        return LangfuseConnector(
            public_key=config.get("public_key", api_key),
            secret_key=api_key,
            host=integration.base_url or config.get("host") or "https://cloud.langfuse.com",
        )
    elif integration.type == IntegrationType.langsmith:
        config = integration.config or {}
        return LangSmithConnector(
            api_key=api_key,
            api_url=integration.base_url or "https://api.smith.langchain.com",
            project=config.get("project"),
        )
    else:
        raise ValueError(f"Unknown integration type: {integration.type}")
