"""Tests for hand-picked feedback selection in the generate-suggestions endpoint.

When ``selected_feedback_ids`` is provided, only those feedback rows feed the
suggestion run — the type/date/limit filters are bypassed. These pin that
behavior plus the input-validation guards.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.models import FeedbackScore, Trace, TraceStatus


@pytest.fixture
def headers(auth_headers, test_project):
    return {**auth_headers, "X-Project-Id": str(test_project.id)}


async def _make_feedback(db_session, test_integration, count: int) -> list:
    """Create `count` traces each with a distinct prompt + one user-feedback score."""
    feedback_ids = []
    for i in range(count):
        t = Trace(
            id=uuid4(),
            integration_id=test_integration.id,
            external_id=f"sel-{i}",
            name="chat",
            input={"messages": [{"role": "user", "content": f"Question number {i}?"}]},
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            status=TraceStatus.success,
        )
        db_session.add(t)
        await db_session.flush()
        fb = FeedbackScore(
            id=uuid4(),
            integration_id=test_integration.id,
            trace_id=t.id,
            external_id=f"sel-fbs-{i}",
            external_trace_id=f"sel-{i}",
            score_name="user-feedback",
            value=float(i % 2),
            scored_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )
        db_session.add(fb)
        feedback_ids.append(fb.id)
    await db_session.commit()
    return feedback_ids


@pytest.mark.asyncio
async def test_selected_feedback_ids_only_uses_picked_rows(
    client, db_session, test_integration, headers, monkeypatch
):
    feedback_ids = await _make_feedback(db_session, test_integration, 5)
    picked = feedback_ids[:2]

    captured = {}

    import app.routers.feedback_suggestion_worker as worker

    def fake_worker(run_id, project_id, suggestions, feedback_comments, feedback_messages, user_settings, db_factory):
        captured["suggestions"] = suggestions

        async def _noop():
            return None

        return _noop()

    monkeypatch.setattr(worker, "run_suggestion_generation", fake_worker)

    resp = await client.post(
        "/api/feedback/generate-suggestions",
        params={"selected_feedback_ids": ",".join(str(i) for i in picked)},
        headers=headers,
    )
    assert resp.status_code == 202, resp.text

    built_ids = {str(s.feedback_id) for s in captured["suggestions"]}
    assert built_ids == {str(i) for i in picked}


@pytest.mark.asyncio
async def test_invalid_selected_feedback_id_returns_400(client, headers):
    resp = await client.post(
        "/api/feedback/generate-suggestions",
        params={"selected_feedback_ids": "not-a-uuid"},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_too_many_selected_feedback_ids_returns_400(client, headers):
    too_many = ",".join(str(uuid4()) for _ in range(201))
    resp = await client.post(
        "/api/feedback/generate-suggestions",
        params={"selected_feedback_ids": too_many},
        headers=headers,
    )
    assert resp.status_code == 400
