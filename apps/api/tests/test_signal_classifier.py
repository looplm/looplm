"""Tests for behavioral signal classification: parser, sampling, and engine wiring."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.models import Integration, Trace, TraceStatus
from app.models.trace_signal import TraceSignal
from app.models.base import SignalType
from app.services.engine.signals import collect_signals
from app.services.signal_classifier import (
    build_trace_repr,
    parse_classification,
)
from app.services.signal_classifier_poller import select_traces_to_classify


# ── Parser ─────────────────────────────────────────────────────────

def test_parse_classification_valid():
    content = json.dumps(
        {"signals": [
            {"type": "refusal", "confidence": 0.9, "detail": "declined"},
            {"type": "loop", "confidence": 1.5, "detail": "repeated"},  # clamps to 1.0
        ]}
    )
    out = parse_classification(content)
    assert {s.signal_type for s in out} == {SignalType.refusal, SignalType.loop}
    loop = next(s for s in out if s.signal_type == SignalType.loop)
    assert loop.confidence == 1.0


def test_parse_classification_drops_unknown_and_dedups():
    content = json.dumps(
        {"signals": [
            {"type": "explicit_failure", "confidence": 0.5},  # not a behavioral type
            {"type": "refusal", "confidence": 0.8},
            {"type": "refusal", "confidence": 0.7},  # duplicate
            "garbage",
        ]}
    )
    out = parse_classification(content)
    assert len(out) == 1
    assert out[0].signal_type == SignalType.refusal


@pytest.mark.parametrize("bad", ["not json", "[]", json.dumps({"signals": "x"}), ""])
def test_parse_classification_garbage(bad):
    assert parse_classification(bad) == []


def test_build_trace_repr_includes_error():
    text = build_trace_repr(
        name="agent", trace_input={"q": "hi"}, trace_output={"a": "no"}, error="boom"
    )
    assert "agent" in text and "boom" in text and "hi" in text


# ── Sampling ───────────────────────────────────────────────────────

def _trace(status=TraceStatus.success):
    return Trace(id=uuid4(), integration_id=uuid4(), external_id="x", status=status)


def test_select_always_includes_failures_even_at_zero_sample():
    fail = _trace(TraceStatus.failure)
    ok = _trace(TraceStatus.success)
    picked = select_traces_to_classify([fail, ok], set(), sample_pct=0, batch_size=10)
    assert fail in picked
    assert ok not in picked


def test_select_includes_important_ids():
    ok = _trace(TraceStatus.success)
    picked = select_traces_to_classify([ok], {ok.id}, sample_pct=0, batch_size=10)
    assert ok in picked


def test_select_full_sample_and_batch_cap():
    traces = [_trace() for _ in range(5)]
    assert len(select_traces_to_classify(traces, set(), sample_pct=100, batch_size=10)) == 5
    assert len(select_traces_to_classify(traces, set(), sample_pct=100, batch_size=2)) == 2


# ── Engine wiring ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collect_signals_includes_behavioral(db_session, test_project, test_integration: Integration):
    t = Trace(
        id=uuid4(),
        integration_id=test_integration.id,
        external_id="beh-1",
        name="support_agent",
        start_time=datetime(2025, 6, 1, tzinfo=timezone.utc),
        status=TraceStatus.success,
    )
    db_session.add(t)
    await db_session.flush()
    db_session.add(
        TraceSignal(
            trace_id=t.id,
            signal_type=SignalType.refusal,
            confidence=0.9,
            detail="assistant declined the request",
        )
    )
    await db_session.commit()

    signals = await collect_signals(db_session, test_project.id)
    behavioral = [s for s in signals if s.signal_type == SignalType.refusal]
    assert len(behavioral) == 1
    assert behavioral[0].trace_id == t.id
    assert behavioral[0].fingerprint_hint == "behavioral:refusal"
