"""Tests for hand-picked feedback selection in the top-questions & themes endpoints.

When ``selected_feedback_ids`` is provided, only those feedback rows feed the
analysis — the date/environment filters and the recency limit are bypassed.
These mirror the suggestions selection tests (test_feedback_suggestions_selection.py)
for the two clustering endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.models import FeedbackScore, Trace, TraceStatus


@pytest.fixture
def headers(auth_headers, test_project):
    return {**auth_headers, "X-Project-Id": str(test_project.id)}


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    """Both endpoints validate LLM config before launching — stub it out so the
    tests don't depend on provider credentials."""
    import app.services.analysis_llm as analysis_llm

    monkeypatch.setattr(analysis_llm, "AnalysisLlmService", lambda user_settings=None: object())


async def _make_feedback(db_session, test_integration, count: int, *, with_comment: bool) -> list:
    """Create `count` traces, each with a distinct user question and one
    user-feedback score (optionally with a comment)."""
    feedback_ids = []
    for i in range(count):
        t = Trace(
            id=uuid4(),
            integration_id=test_integration.id,
            external_id=f"ana-{i}",
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
            external_id=f"ana-fbs-{i}",
            external_trace_id=f"ana-{i}",
            score_name="user-feedback",
            value=float(i % 2),
            comment=(f"Comment number {i}" if with_comment else None),
            scored_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )
        db_session.add(fb)
        feedback_ids.append(fb.id)
    await db_session.commit()
    return feedback_ids


@pytest.mark.asyncio
async def test_top_questions_selection_only_uses_picked_rows(
    client, db_session, test_integration, headers, monkeypatch
):
    feedback_ids = await _make_feedback(db_session, test_integration, 8, with_comment=False)
    picked = feedback_ids[:5]

    captured = {}
    import app.routers.top_questions as tq_router

    def fake_worker(analysis_id, questions, user_settings, db_factory):
        captured["questions"] = questions

        async def _noop():
            return None

        return _noop()

    monkeypatch.setattr(tq_router, "run_top_questions_analysis", fake_worker)

    resp = await client.post(
        "/api/feedback/top-questions",
        # A future from_date would exclude every row if it were honored — proves
        # the date filter is bypassed when a selection is given.
        json={
            "selected_feedback_ids": [str(i) for i in picked],
            "from_date": "2099-01-01T00:00:00Z",
        },
        headers=headers,
    )
    assert resp.status_code == 202, resp.text

    built_ids = {q["feedback_id"] for q in captured["questions"]}
    assert built_ids == {str(i) for i in picked}


@pytest.mark.asyncio
async def test_themes_selection_only_uses_picked_rows(
    client, db_session, test_integration, headers, monkeypatch
):
    feedback_ids = await _make_feedback(db_session, test_integration, 8, with_comment=True)
    picked = feedback_ids[:5]

    captured = {}
    import app.routers.feedback_themes as themes_router

    def fake_worker(analysis_id, comments, user_settings, db_factory):
        captured["comments"] = comments

        async def _noop():
            return None

        return _noop()

    monkeypatch.setattr(themes_router, "run_feedback_themes_analysis", fake_worker)

    resp = await client.post(
        "/api/feedback/themes",
        json={
            "selected_feedback_ids": [str(i) for i in picked],
            "from_date": "2099-01-01T00:00:00Z",
        },
        headers=headers,
    )
    assert resp.status_code == 202, resp.text

    built_ids = {c["feedback_id"] for c in captured["comments"]}
    assert built_ids == {str(i) for i in picked}


@pytest.mark.asyncio
async def test_top_questions_too_many_selected_returns_400(client, headers):
    too_many = [str(uuid4()) for _ in range(201)]
    resp = await client.post(
        "/api/feedback/top-questions",
        json={"selected_feedback_ids": too_many},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_themes_too_many_selected_returns_400(client, headers):
    too_many = [str(uuid4()) for _ in range(201)]
    resp = await client.post(
        "/api/feedback/themes",
        json={"selected_feedback_ids": too_many},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_top_questions_selection_below_minimum_returns_400(
    client, db_session, test_integration, headers
):
    """Fewer than 5 usable selected rows hits the existing minimum-questions guard."""
    feedback_ids = await _make_feedback(db_session, test_integration, 5, with_comment=False)
    picked = feedback_ids[:2]
    resp = await client.post(
        "/api/feedback/top-questions",
        json={"selected_feedback_ids": [str(i) for i in picked]},
        headers=headers,
    )
    assert resp.status_code == 400
