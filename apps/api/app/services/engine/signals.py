"""Signal collection — the input side of issue detection.

Unifies four production signal sources into one normalized ``Signal`` stream
that the clustering step groups into issues:

- explicit failures      — ``Trace.status == failure`` / error spans
- eval failures          — ``EvalResult.pass_ == False`` (auto-grade & offline runs)
- negative feedback      — low ``FeedbackScore.value``
- latency anomalies      — traces far above the integration's trailing mean

Each source is best-effort and independently bounded so one noisy source can't
crowd out the others. JSONB fields (``result_metadata``) are parsed in Python
rather than via Postgres operators so the SQLite-backed test suite exercises
the same code path.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    EvalResult,
    EvalRun,
    FeedbackScore,
    Integration,
    SignalType,
    Trace,
    TraceSignal,
    TraceStatus,
)

logger = logging.getLogger(__name__)

# A feedback score at or below this is treated as negative. Matches the dashboard
# convention where 1 == positive and 0 == negative for boolean scores; numeric
# scores below the midpoint count as negative too.
NEGATIVE_FEEDBACK_THRESHOLD = 0.5

# Per-source caps so a single source can't dominate a detection batch.
PER_SOURCE_LIMIT = 200

# Latency anomaly: need a baseline and a clear outlier before flagging.
_ANOMALY_MIN_SAMPLES = 20
_ANOMALY_Z = 3.0


@dataclass
class Signal:
    """One normalized production failure signal, ready for clustering."""

    signal_type: SignalType
    summary: str                      # short human-readable description for the LLM grouper
    occurred_at: datetime | None
    trace_id: UUID | None = None
    detail: str | None = None         # longer context (error text, feedback comment, …)
    fingerprint_hint: str = ""        # deterministic key for dedup / fallback clustering
    meta: dict[str, Any] = field(default_factory=dict)


def _truncate(value: Any, limit: int = 400) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _as_dict(value: Any) -> dict[str, Any]:
    """result_metadata may arrive as a dict (Postgres JSONB) or a str (SQLite TEXT)."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


async def _project_integration_ids(db: AsyncSession, project_id: UUID) -> list[UUID]:
    rows = await db.execute(
        select(Integration.id).where(Integration.project_id == project_id)
    )
    return list(rows.scalars().all())


async def collect_signals(
    db: AsyncSession,
    project_id: UUID,
    *,
    since: datetime | None = None,
    integration_ids: list[UUID] | None = None,
) -> list[Signal]:
    """Gather production failure signals for a project since ``since`` (default: all time)."""
    ids = integration_ids or await _project_integration_ids(db, project_id)
    if not ids:
        return []

    signals: list[Signal] = []
    signals += await _explicit_failures(db, ids, since)
    signals += await _eval_failures(db, project_id, ids, since)
    signals += await _negative_feedback(db, ids, since)
    signals += await _latency_anomalies(db, ids, since)
    signals += await _behavioral_signals(db, ids, since)
    return signals


# Human-readable phrasing for the LLM-classified behavioral signal types.
_BEHAVIORAL_LABEL = {
    SignalType.refusal: "Assistant refused the request",
    SignalType.user_frustration: "User frustration",
    SignalType.task_incomplete: "Task left incomplete",
    SignalType.loop: "Agent stuck in a loop",
}


async def _behavioral_signals(
    db: AsyncSession, ids: list[UUID], since: datetime | None
) -> list[Signal]:
    """Behavioral signals (refusal/frustration/…) classified onto traces by the LLM."""
    query = (
        select(TraceSignal, Trace)
        .join(Trace, TraceSignal.trace_id == Trace.id)
        .where(Trace.integration_id.in_(ids))
    )
    if since:
        query = query.where(TraceSignal.created_at > since)
    query = query.order_by(TraceSignal.created_at.desc()).limit(PER_SOURCE_LIMIT)

    rows = (await db.execute(query)).all()
    out: list[Signal] = []
    for sig, trace in rows:
        label = _BEHAVIORAL_LABEL.get(sig.signal_type, sig.signal_type.value)
        name = trace.name or "trace"
        summary = f"{label} on '{name}'"
        if sig.detail:
            summary += f": {sig.detail}"
        out.append(
            Signal(
                signal_type=sig.signal_type,
                summary=_truncate(summary),
                occurred_at=trace.start_time or trace.created_at,
                trace_id=trace.id,
                detail=sig.detail,
                fingerprint_hint=f"behavioral:{sig.signal_type.value}",
                meta={"confidence": sig.confidence},
            )
        )
    return out


async def _explicit_failures(
    db: AsyncSession, ids: list[UUID], since: datetime | None
) -> list[Signal]:
    query = select(Trace).where(
        Trace.integration_id.in_(ids),
        Trace.status == TraceStatus.failure,
        Trace.parent_trace_id.is_(None),  # root traces only
    )
    if since:
        query = query.where(Trace.created_at > since)
    query = query.order_by(Trace.created_at.desc()).limit(PER_SOURCE_LIMIT)

    rows = (await db.execute(query)).scalars().all()
    out: list[Signal] = []
    for t in rows:
        err = _truncate(t.error_message) if t.error_message else None
        name = t.name or "trace"
        summary = f"Trace '{name}' failed"
        if err:
            summary += f": {err}"
        out.append(
            Signal(
                signal_type=SignalType.explicit_failure,
                summary=_truncate(summary),
                occurred_at=t.start_time or t.created_at,
                trace_id=t.id,
                detail=err,
                fingerprint_hint=f"explicit:{_error_class(t.error_message)}",
                meta={"trace_name": name},
            )
        )
    return out


def _error_class(error_message: str | None) -> str:
    """Cheap deterministic bucket for an error string (first token / known keywords)."""
    if not error_message:
        return "error"
    msg = error_message.lower()
    for key in ("timeout", "rate limit", "connection", "context", "token", "permission", "not found"):
        if key in msg:
            return key.replace(" ", "_")
    return error_message.split(":", 1)[0].strip().lower()[:48] or "error"


async def _eval_failures(
    db: AsyncSession, project_id: UUID, ids: list[UUID], since: datetime | None
) -> list[Signal]:
    query = (
        select(EvalResult, EvalRun.source)
        .join(EvalRun, EvalResult.run_id == EvalRun.id)
        .where(EvalRun.project_id == project_id, EvalResult.pass_.is_(False))
    )
    if since:
        query = query.where(EvalRun.created_at > since)
    query = query.order_by(EvalRun.created_at.desc()).limit(PER_SOURCE_LIMIT)

    rows = (await db.execute(query)).all()
    out: list[Signal] = []
    for result, source in rows:
        meta = _as_dict(result.result_metadata)
        root_cause = meta.get("root_cause") if isinstance(meta.get("root_cause"), dict) else {}
        category = root_cause.get("category")
        pattern = meta.get("failure_pattern")
        bucket = category or pattern or "unknown"

        trace_id = _coerce_uuid(meta.get("trace_id"))
        reason = result.reason or root_cause.get("evidence")

        summary = f"Eval failure ({bucket})"
        if reason:
            summary += f": {_truncate(reason, 200)}"

        out.append(
            Signal(
                signal_type=SignalType.eval_failure,
                summary=_truncate(summary),
                occurred_at=result.created_at,
                trace_id=trace_id,
                detail=_truncate(reason) if reason else None,
                fingerprint_hint=f"eval:{bucket}",
                meta={
                    "source": source,
                    "failure_pattern": pattern,
                    "root_cause_category": category,
                    "grader_pattern": meta.get("grader_pattern"),
                },
            )
        )
    return out


def _coerce_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str) and value:
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


async def _negative_feedback(
    db: AsyncSession, ids: list[UUID], since: datetime | None
) -> list[Signal]:
    query = select(FeedbackScore).where(
        FeedbackScore.integration_id.in_(ids),
        FeedbackScore.value <= NEGATIVE_FEEDBACK_THRESHOLD,
    )
    if since:
        query = query.where(FeedbackScore.created_at > since)
    query = query.order_by(FeedbackScore.created_at.desc()).limit(PER_SOURCE_LIMIT)

    rows = (await db.execute(query)).scalars().all()
    out: list[Signal] = []
    for fb in rows:
        comment = _truncate(fb.comment) if fb.comment else None
        summary = f"Negative feedback on '{fb.score_name}' (score {fb.value:g})"
        if comment:
            summary += f": {comment}"
        out.append(
            Signal(
                signal_type=SignalType.negative_feedback,
                summary=_truncate(summary),
                occurred_at=fb.scored_at or fb.created_at,
                trace_id=fb.trace_id,
                detail=comment,
                fingerprint_hint=f"feedback:{fb.score_name}",
                meta={"score_name": fb.score_name, "value": fb.value},
            )
        )
    return out


async def _latency_anomalies(
    db: AsyncSession, ids: list[UUID], since: datetime | None
) -> list[Signal]:
    """Flag root traces whose duration is a strong positive outlier vs the window mean.

    Best-effort and cheap: one pass over recent successful root traces to build a
    baseline, then z-score each. Skipped entirely below ``_ANOMALY_MIN_SAMPLES``.
    """
    query = select(Trace).where(
        Trace.integration_id.in_(ids),
        Trace.parent_trace_id.is_(None),
        Trace.duration_ms.isnot(None),
    )
    if since:
        query = query.where(Trace.created_at > since)
    query = query.order_by(Trace.created_at.desc()).limit(PER_SOURCE_LIMIT * 5)

    rows = (await db.execute(query)).scalars().all()
    durations = [t.duration_ms for t in rows if t.duration_ms is not None]
    if len(durations) < _ANOMALY_MIN_SAMPLES:
        return []

    mean = sum(durations) / len(durations)
    variance = sum((d - mean) ** 2 for d in durations) / len(durations)
    std = math.sqrt(variance)
    if std <= 0:
        return []

    out: list[Signal] = []
    for t in rows:
        if t.duration_ms is None:
            continue
        z = (t.duration_ms - mean) / std
        if z < _ANOMALY_Z:
            continue
        out.append(
            Signal(
                signal_type=SignalType.anomaly,
                summary=_truncate(
                    f"Latency anomaly: trace '{t.name or 'trace'}' took {t.duration_ms}ms "
                    f"(~{z:.1f}σ above the {round(mean)}ms mean)"
                ),
                occurred_at=t.start_time or t.created_at,
                trace_id=t.id,
                detail=None,
                fingerprint_hint="anomaly:latency",
                meta={"duration_ms": t.duration_ms, "z": round(z, 2)},
            )
        )
    return out
