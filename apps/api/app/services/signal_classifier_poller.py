"""Background poller that classifies behavioral signals on a sample of traces.

Every ``signal_classify_interval_minutes`` it scans recent unclassified root
traces, picks a sample to send to the LLM (always including failures and
negatively-rated traces, plus a configurable percentage of the rest), writes any
detected ``TraceSignal`` rows, and watermarks every scanned trace via
``Trace.signals_classified_at`` so it is considered exactly once.

Gated by ``settings.signal_classify_enabled`` (off by default — it spends LLM
tokens). Uses app-level LLM credentials; if none are configured the poller
no-ops gracefully.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.config import settings
from app.db import async_session
from app.models.models import FeedbackScore, Integration, Trace, TraceStatus
from app.models.trace_signal import TraceSignal
from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService
from app.services.llm_usage_tracker import record_llm_usage
from app.services.signal_classifier import build_trace_repr, classify_trace

logger = logging.getLogger(__name__)

_poller_task: asyncio.Task | None = None

NEGATIVE_FEEDBACK_THRESHOLD = 0.5


async def start_signal_classifier_poller() -> None:
    """Start the background loop (called from app lifespan). No-op if disabled."""
    global _poller_task
    if not settings.signal_classify_enabled:
        logger.info("Signal classifier poller disabled (signal_classify_enabled=False)")
        return
    _poller_task = asyncio.create_task(_poll_loop())
    logger.info("Signal classifier poller started")


async def stop_signal_classifier_poller() -> None:
    global _poller_task
    if _poller_task:
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            pass
        _poller_task = None
    logger.info("Signal classifier poller stopped")


async def _poll_loop() -> None:
    interval = max(1, settings.signal_classify_interval_minutes) * 60
    while True:
        try:
            await classify_pending_batch()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Signal classifier poller error")
        await asyncio.sleep(interval)


def select_traces_to_classify(
    candidates: list[Trace],
    important_ids: set[UUID],
    *,
    sample_pct: int,
    batch_size: int,
) -> list[Trace]:
    """Pick which scanned traces to actually classify.

    Always picks failures and traces in ``important_ids`` (e.g. negatively-rated);
    otherwise includes a deterministic ``sample_pct`` slice (by trace id) so the
    same trace is consistently in or out regardless of when it's scanned.
    """
    picked: list[Trace] = []
    for t in candidates:
        if len(picked) >= batch_size:
            break
        important = t.status == TraceStatus.failure or t.id in important_ids
        sampled = (int(t.id.hex, 16) % 100) < sample_pct
        if important or sampled:
            picked.append(t)
    return picked


async def classify_pending_batch() -> int:
    """Classify one batch of pending traces. Returns the number classified."""
    async with async_session() as db:
        # Each project uses its own shared LLM credentials, falling back to the
        # instance env key. Built lazily and cached per project for this batch.
        _llm_cache: dict[UUID, AnalysisLlmService | None] = {}

        async def _llm_for_project(pid: UUID) -> AnalysisLlmService | None:
            if pid not in _llm_cache:
                project_settings = await AnalysisLlmService.load_project_settings(db, pid)
                try:
                    _llm_cache[pid] = AnalysisLlmService(project_settings=project_settings)
                except AnalysisLlmConfigError:
                    _llm_cache[pid] = None
            return _llm_cache[pid]

        rows = (
            await db.execute(
                select(Trace, Integration.project_id)
                .join(Integration, Trace.integration_id == Integration.id)
                .where(
                    Trace.signals_classified_at.is_(None),
                    Trace.parent_trace_id.is_(None),
                )
                .order_by(Trace.created_at.desc())
                .limit(settings.signal_classify_scan_limit)
            )
        ).all()
        if not rows:
            return 0

        candidates = [t for t, _ in rows]
        project_by_trace: dict[UUID, UUID] = {t.id: pid for t, pid in rows}

        trace_ids = [t.id for t in candidates]
        fb_rows = (
            await db.execute(
                select(FeedbackScore.trace_id).where(
                    FeedbackScore.trace_id.in_(trace_ids),
                    FeedbackScore.value <= NEGATIVE_FEEDBACK_THRESHOLD,
                )
            )
        ).scalars().all()
        important_ids = {tid for tid in fb_rows if tid is not None}

        picked = select_traces_to_classify(
            candidates,
            important_ids,
            sample_pct=settings.signal_classify_sample_pct,
            batch_size=settings.signal_classify_batch_size,
        )

        # Classify the picked traces. Any LLM call raising is treated as an
        # infrastructure failure: abort without watermarking so the batch retries.
        # Traces whose project has no LLM configured are left unwatermarked so
        # they get picked up once a key is added.
        classified = 0
        try:
            for t in picked:
                llm = await _llm_for_project(project_by_trace[t.id])
                if llm is None:
                    continue
                repr_text = build_trace_repr(
                    name=t.name,
                    trace_input=t.input,
                    trace_output=t.output,
                    error=t.error_message,
                )
                detected, usage = await classify_trace(repr_text, llm)
                await record_llm_usage(
                    db,
                    project_id=project_by_trace[t.id],
                    service_name="signal_classifier",
                    function_name="classify_trace",
                    provider=llm.provider,
                    model=llm.model,
                    usage=usage,
                )
                classified += 1
                for sig in detected:
                    db.add(
                        TraceSignal(
                            trace_id=t.id,
                            signal_type=sig.signal_type,
                            confidence=sig.confidence,
                            detail=sig.detail,
                        )
                    )
        except Exception:
            logger.exception("Signal classifier: LLM batch failed; aborting")
            await db.rollback()
            return 0

        # Watermark scanned candidates whose project has an LLM configured — each
        # is considered exactly once. Candidates from projects with no LLM stay
        # pending so they are classified once a key is configured.
        now = datetime.now(timezone.utc)
        watermarked = 0
        for t in candidates:
            if await _llm_for_project(project_by_trace[t.id]) is None:
                continue
            t.signals_classified_at = now
            watermarked += 1
        await db.commit()

        logger.info(
            "Signal classifier: scanned %d, classified %d", watermarked, classified
        )
        return classified
