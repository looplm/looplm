"""Unit tests for retrieval-frequency analysis: pure tails + trace counting."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.base import SpanType, TraceStatus
from app.models.integrations import Span, Trace
from app.services.chunk_retrieval_frequency import (
    analyze_frequency,
    frequency_from_traces,
)


# ── Pure tail analysis ───────────────────────────────────────────────────────

def test_dead_and_hot_tails():
    sampled = {"a", "b", "c", "d"}
    counter = Counter({"a": 30, "b": 1, "elsewhere": 5})
    metrics, findings = analyze_frequency(
        counter, sampled, source="traces", window_days=30, events_scanned=100,
        titles_by_id={"a": "Disclaimer"},
    )
    assert metrics["available"]
    # hot threshold = max(10, 20% of 100) = 20 → only "a" qualifies.
    assert metrics["hot_threshold"] == 20
    assert metrics["hot"] == 1
    assert metrics["top_hot"][0] == {"chunk_id": "a", "count": 30, "title": "Disclaimer"}
    # c and d were never retrieved → 50% dead → warn fires.
    assert metrics["dead"] == 2
    assert metrics["dead_pct"] == 50.0
    assert any(f.title == "Large dead-chunk fraction" for f in findings)
    assert any(f.title == "Hot generic chunks" for f in findings)
    # Histogram covers exactly the sampled population.
    assert sum(b["count"] for b in metrics["histogram"]) == len(sampled)
    # Retrieved-but-unsampled chunks still count in the unique total.
    assert metrics["unique_chunks_retrieved"] == 3


def test_no_events_is_unavailable():
    metrics, findings = analyze_frequency(
        Counter(), {"a"}, source="traces", window_days=30, events_scanned=0
    )
    assert metrics["available"] is False
    assert findings == []


def test_small_windows_use_minimum_hot_threshold():
    sampled = {"a", "b"}
    counter = Counter({"a": 9})
    metrics, _ = analyze_frequency(
        counter, sampled, source="probe", window_days=None, events_scanned=20
    )
    # max(10, 20% of 20 = 4) = 10 → 9 hits is not hot.
    assert metrics["hot_threshold"] == 10
    assert metrics["hot"] == 0


# ── Counting from trace spans ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_frequency_from_traces_counts_chunks_once_per_event(
    db_session, test_project, test_integration
):
    now = datetime.now(timezone.utc)
    for i, sources in enumerate((
        [{"chunkId": "c1"}, {"chunkId": "c2"}, {"chunkId": "c1"}],  # c1 deduped within event
        [{"chunkId": "c1"}],
        [],  # no sources → not an event
    )):
        trace = Trace(
            id=uuid4(), integration_id=test_integration.id, external_id=f"freq-{i}",
            name=f"trace-{i}", start_time=now - timedelta(days=1), status=TraceStatus.success,
        )
        db_session.add(trace)
        await db_session.flush()
        db_session.add(Span(
            id=uuid4(), trace_id=trace.id, name="retrieval-context",
            type=SpanType.retriever, output={"sources": sources}, status="ok",
        ))
    # An old trace outside the window must not count.
    old = Trace(
        id=uuid4(), integration_id=test_integration.id, external_id="freq-old",
        name="old", start_time=now - timedelta(days=90), status=TraceStatus.success,
    )
    db_session.add(old)
    await db_session.flush()
    db_session.add(Span(
        id=uuid4(), trace_id=old.id, name="retrieval-context",
        type=SpanType.retriever, output={"sources": [{"chunkId": "c9"}]}, status="ok",
    ))
    await db_session.commit()

    counter, events = await frequency_from_traces(db_session, test_project, window_days=30)
    assert events == 2
    assert counter == Counter({"c1": 2, "c2": 1})
