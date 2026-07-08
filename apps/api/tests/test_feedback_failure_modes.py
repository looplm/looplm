"""Tests for the failure-mode analysis endpoint + worker helpers.

Covers hand-picked selection (selection IS the filter), the too-many / minimum
guards, and the lossless clustering logic in the worker. Mirrors
test_feedback_analysis_selection.py for the themes/top-questions endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.models import FeedbackScore, Trace, TraceStatus
from app.routers.feedback_failure_modes_worker import (
    _build_clusters,
    _parse_json_object,
)


@pytest.fixture
def headers(auth_headers, test_project):
    return {**auth_headers, "X-Project-Id": str(test_project.id)}


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    """The endpoint validates LLM config before launching — stub it out."""
    import app.services.analysis_llm as analysis_llm

    monkeypatch.setattr(analysis_llm, "AnalysisLlmService", lambda user_settings=None: object())


async def _make_feedback(db_session, test_integration, count: int) -> list[tuple]:
    """Create `count` traces each with one user-feedback score. Returns
    (feedback_id, trace_id) pairs. Alternating positive/negative values."""
    pairs = []
    for i in range(count):
        t = Trace(
            id=uuid4(),
            integration_id=test_integration.id,
            external_id=f"fm-{i}",
            name="chat",
            input={"messages": [{"role": "user", "content": f"Question number {i}?"}]},
            output={"output": f"Answer number {i}"},
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            status=TraceStatus.success,
        )
        db_session.add(t)
        await db_session.flush()
        fb = FeedbackScore(
            id=uuid4(),
            integration_id=test_integration.id,
            trace_id=t.id,
            external_id=f"fm-fbs-{i}",
            external_trace_id=f"fm-{i}",
            score_name="user-feedback",
            value=float(i % 2),
            comment=f"Complaint number {i}",
            scored_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )
        db_session.add(fb)
        pairs.append((fb.id, t.id))
    await db_session.commit()
    return pairs


@pytest.mark.asyncio
async def test_failure_modes_selection_only_uses_picked_rows(
    client, db_session, test_integration, headers, monkeypatch
):
    pairs = await _make_feedback(db_session, test_integration, 8)
    picked = pairs[:5]

    captured = {}
    import app.routers.feedback_failure_modes as fm_router

    def fake_worker(analysis_id, cases, user_settings, db_factory):
        captured["cases"] = cases

        async def _noop():
            return None

        return _noop()

    monkeypatch.setattr(fm_router, "run_failure_mode_analysis", fake_worker)

    resp = await client.post(
        "/api/feedback/failure-modes",
        # A future from_date would exclude every row if honored — proves the date
        # filter is bypassed (and the positive-value default filter too) when a
        # selection is given.
        json={
            "selected_feedback_ids": [str(fb) for fb, _ in picked],
            "from_date": "2099-01-01T00:00:00Z",
        },
        headers=headers,
    )
    assert resp.status_code == 202, resp.text

    built_trace_ids = {c["trace_id"] for c in captured["cases"]}
    assert built_trace_ids == {str(tr) for _, tr in picked}
    # Each case carries the serialized diagnosis payload for the worker.
    assert all(c.get("serialized") for c in captured["cases"])


@pytest.mark.asyncio
async def test_failure_modes_too_many_selected_returns_400(client, headers):
    too_many = [str(uuid4()) for _ in range(201)]
    resp = await client.post(
        "/api/feedback/failure-modes",
        json={"selected_feedback_ids": too_many},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_failure_modes_below_minimum_returns_400(
    client, db_session, test_integration, headers
):
    """Fewer than 2 usable traces hits the minimum-traces guard."""
    pairs = await _make_feedback(db_session, test_integration, 3)
    picked = pairs[:1]
    resp = await client.post(
        "/api/feedback/failure-modes",
        json={"selected_feedback_ids": [str(fb) for fb, _ in picked]},
        headers=headers,
    )
    assert resp.status_code == 400


def test_build_clusters_is_lossless():
    """Every diagnosed case must land in exactly one cluster, even ones the LLM
    forgets to assign."""
    cases = [
        {"trace_id": f"t{i}", "category": "retrieval" if i < 3 else "generation",
         "question": f"q{i}", "explanation": "e", "confidence": 0.9}
        for i in range(5)
    ]
    # LLM only assigned the first 3 to a cluster and dropped indices 4, 5.
    raw = [{"label": "Missing docs", "category": "retrieval",
            "description": "d", "recommendation": "r", "case_indices": [1, 2, 3]}]

    clusters = _build_clusters(raw, cases)

    total = sum(c["count"] for c in clusters)
    assert total == len(cases)  # nothing dropped
    assert clusters[0]["rank"] == 1
    # The unassigned generation cases get a fallback cluster.
    assert any(c["category"] == "generation" for c in clusters)


def test_build_clusters_ignores_out_of_range_indices():
    cases = [{"trace_id": "t0", "category": "query", "question": "q", "explanation": "e",
              "confidence": None}]
    raw = [{"label": "X", "category": "query", "case_indices": [1, 99, 0, -1]}]
    clusters = _build_clusters(raw, cases)
    assert sum(c["count"] for c in clusters) == 1


def test_parse_json_object_handles_fences():
    assert _parse_json_object('{"category": "retrieval"}')["category"] == "retrieval"
    fenced = 'here you go:\n```json\n{"category": "generation"}\n```'
    assert _parse_json_object(fenced)["category"] == "generation"
    assert _parse_json_object("not json at all") == {}
