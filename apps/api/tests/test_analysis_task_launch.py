"""Regression tests for background-analysis task launch.

The analyze endpoints used to only flush (not commit) the analysis row before
spawning the worker task. The worker reads the row from its own session, where
an uncommitted row is invisible — on Postgres the task crashed with
``AttributeError: 'NoneType' object has no attribute 'status'`` and the
analysis sat at 'pending' forever (the UI's "Starting analysis..." freeze).

These tests pin both halves of the fix: the route commits before spawning the
task, and the workers abort cleanly (cleaning up their task registry) when the
row is missing instead of crashing outside their try block.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.models import FeedbackScore, Trace, TraceStatus
from tests.conftest import TestSessionLocal


@pytest.fixture
def headers(auth_headers, test_project):
    return {**auth_headers, "X-Project-Id": str(test_project.id)}


@pytest.mark.asyncio
async def test_top_questions_worker_aborts_cleanly_on_missing_row():
    from app.routers.top_questions_worker import _top_questions_tasks, run_top_questions_analysis

    missing_id = uuid4()
    _top_questions_tasks[missing_id] = None  # simulated registry entry
    # Must not raise, and must clean up the registry entry.
    await run_top_questions_analysis(
        analysis_id=missing_id, questions=[], user_settings=None, db_factory=TestSessionLocal
    )
    assert missing_id not in _top_questions_tasks


@pytest.mark.asyncio
async def test_feedback_themes_worker_aborts_cleanly_on_missing_row():
    from app.routers.feedback_themes_worker import (
        _feedback_theme_tasks,
        run_feedback_themes_analysis,
    )

    missing_id = uuid4()
    _feedback_theme_tasks[missing_id] = None
    await run_feedback_themes_analysis(
        analysis_id=missing_id, comments=[], user_settings=None, db_factory=TestSessionLocal
    )
    assert missing_id not in _feedback_theme_tasks


@pytest.mark.asyncio
async def test_request_clusters_worker_aborts_cleanly_on_missing_row():
    from app.routers.request_clusters_worker import (
        _request_cluster_tasks,
        run_request_cluster_analysis,
    )

    missing_id = uuid4()
    _request_cluster_tasks[missing_id] = None
    await run_request_cluster_analysis(
        analysis_id=missing_id, requests=[], user_settings=None, db_factory=TestSessionLocal
    )
    assert missing_id not in _request_cluster_tasks


@pytest.mark.asyncio
async def test_top_questions_route_commits_before_spawning_worker(
    client, db_session, test_integration, headers, monkeypatch
):
    """The analysis row must be committed by the time the worker is spawned."""
    for i in range(5):
        t = Trace(
            id=uuid4(),
            integration_id=test_integration.id,
            external_id=f"fb-{i}",
            name="chat",
            input={"messages": [{"role": "user", "content": f"How do I do thing {i}?"}]},
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            status=TraceStatus.success,
        )
        db_session.add(t)
        await db_session.flush()
        db_session.add(
            FeedbackScore(
                id=uuid4(),
                integration_id=test_integration.id,
                trace_id=t.id,
                external_id=f"fbs-{i}",
                external_trace_id=f"fb-{i}",
                score_name="user-feedback",
                value=float(i % 2),
                scored_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
            )
        )
    await db_session.commit()

    # The route validates LLM config before launching — stub it out so the
    # test doesn't depend on provider credentials.
    import app.services.analysis_llm as analysis_llm

    monkeypatch.setattr(analysis_llm, "AnalysisLlmService", lambda user_settings=None: object())

    # Spy on the request session's commit, and record its state at the moment
    # the worker coroutine is created (the create_task call site).
    import app.routers.top_questions as tq_router

    state = {"committed": False, "committed_at_spawn": None}
    real_commit = db_session.commit

    async def tracking_commit():
        state["committed"] = True
        await real_commit()

    monkeypatch.setattr(db_session, "commit", tracking_commit)

    def fake_worker(analysis_id, questions, user_settings, db_factory):
        state["committed_at_spawn"] = state["committed"]

        async def _noop():
            return None

        return _noop()

    monkeypatch.setattr(tq_router, "run_top_questions_analysis", fake_worker)

    resp = await client.post("/api/feedback/top-questions", json={"limit": 50}, headers=headers)
    assert resp.status_code == 202, resp.text
    assert state["committed_at_spawn"] is True
