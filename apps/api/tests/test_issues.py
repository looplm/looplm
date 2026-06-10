"""Tests for issue detection: signal collection, clustering upsert, recurrence, API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.models import (
    FeedbackScore,
    Integration,
    Issue,
    IssueStatus,
    SignalType,
    Span,
    SpanType,
    Trace,
    TraceStatus,
)
from app.services.engine.clustering import (
    cluster_signals,
    parse_clustering_response,
)
from app.services.engine.engine_service import detect_issues
from app.services.engine.signals import collect_signals


# ── Fakes ──────────────────────────────────────────────────────────

class FakeLlm:
    """Stands in for AnalysisLlmService.

    Reads the NEW signals / EXISTING issues out of the user message and returns
    a single group covering all signals — matching the first existing issue when
    one is offered, otherwise creating a new one. Records how many times it ran.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def tracked_chat_completion(self, messages, **kwargs):
        self.calls += 1
        user = messages[-1]["content"]
        existing_part, new_part = user.split("\n\nNEW signals:\n", 1)
        existing = json.loads(existing_part.split("EXISTING issues:\n", 1)[1])
        new = json.loads(new_part)

        group = {
            "title": "Search tool keeps failing",
            "category": "tool_failure",
            "severity": "high",
            "existing_issue_id": existing[0]["id"] if existing else None,
            "signal_indices": [s["index"] for s in new],
        }
        return json.dumps({"groups": [group]}), None


# ── Fixtures ───────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def failing_data(db_session, test_integration: Integration):
    """Two failing traces (similar error) + one negative-feedback score."""
    traces = []
    for i in range(2):
        t = Trace(
            id=uuid4(),
            integration_id=test_integration.id,
            external_id=f"fail-{i}",
            name="support_agent",
            start_time=datetime(2025, 6, 1, tzinfo=timezone.utc),
            status=TraceStatus.failure,
            error_message="ToolError: search timeout after 30s",
        )
        db_session.add(t)
        await db_session.flush()
        db_session.add(
            Span(
                id=uuid4(), trace_id=t.id, name="search_tool", type=SpanType.tool,
                duration_ms=30000, status="error",
                error_message="timeout",
            )
        )
        traces.append(t)

    # A successful trace (should not produce a signal)
    ok = Trace(
        id=uuid4(), integration_id=test_integration.id, external_id="ok-1",
        name="support_agent", start_time=datetime(2025, 6, 1, tzinfo=timezone.utc),
        status=TraceStatus.success,
    )
    db_session.add(ok)
    await db_session.flush()

    fb = FeedbackScore(
        id=uuid4(),
        integration_id=test_integration.id,
        trace_id=traces[0].id,
        external_id="fb-1",
        external_trace_id="fail-0",
        score_name="user-feedback",
        value=0.0,
        data_type="BOOLEAN",
        comment="bot couldn't cancel my subscription",
        scored_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    db_session.add(fb)
    await db_session.commit()
    return {"integration": test_integration, "traces": traces}


# ── Signal collection ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collect_signals_picks_up_failures_and_feedback(
    db_session, test_project, failing_data
):
    signals = await collect_signals(db_session, test_project.id)

    by_type = {}
    for s in signals:
        by_type.setdefault(s.signal_type, []).append(s)

    # The successful trace produced no explicit-failure signal (only the 2 failures).
    assert len(by_type[SignalType.explicit_failure]) == 2
    assert len(by_type[SignalType.negative_feedback]) == 1
    # Fingerprint hints bucket the timeout errors together.
    assert all(
        s.fingerprint_hint == "explicit:timeout"
        for s in by_type[SignalType.explicit_failure]
    )


@pytest.mark.asyncio
async def test_collect_signals_empty_for_project_without_integrations(db_session, test_project):
    signals = await collect_signals(db_session, test_project.id, integration_ids=[])
    assert signals == []


# ── Clustering parse (pure) ────────────────────────────────────────

def test_parse_clustering_response_validates_and_buckets_missing():
    existing_id = uuid4()
    content = json.dumps(
        {
            "groups": [
                {
                    "title": "Cancellation handling broken",
                    "category": "unhandled_request",
                    "severity": "high",
                    "existing_issue_id": str(existing_id),
                    "signal_indices": [0, 1, 99],  # 99 is out of range, dropped
                },
                {
                    "title": "bad",
                    "severity": "nonsense",  # normalizes to medium
                    "existing_issue_id": str(uuid4()),  # unknown id -> treated as new
                    "signal_indices": [2],
                },
            ]
        }
    )
    groups = parse_clustering_response(content, n_signals=4, existing_ids={existing_id})

    g0 = groups[0]
    assert g0.signal_indices == [0, 1]
    assert g0.existing_issue_id == existing_id
    assert g0.severity.value == "high"

    g1 = groups[1]
    assert g1.severity.value == "medium"
    assert g1.existing_issue_id is None

    # Index 3 was omitted by the model -> bucketed into a catch-all group.
    bucketed = [i for g in groups for i in g.signal_indices]
    assert sorted(bucketed) == [0, 1, 2, 3]


def test_parse_clustering_response_handles_garbage():
    assert parse_clustering_response("not json", 3, set()) == []


@pytest.mark.asyncio
async def test_cluster_signals_falls_back_without_llm(db_session, test_project, failing_data):
    signals = await collect_signals(db_session, test_project.id)
    groups, usage = await cluster_signals(signals, [], llm=None)
    assert usage is None
    assert groups  # deterministic fallback still groups everything
    covered = sorted(i for g in groups for i in g.signal_indices)
    assert covered == list(range(len(signals)))


# ── End-to-end detection + upsert + recurrence ─────────────────────

@pytest.mark.asyncio
async def test_detect_issues_creates_then_recurs(db_session, test_project, failing_data):
    fake = FakeLlm()

    # First pass: no existing issues -> create one.
    result1 = await detect_issues(db_session, test_project.id, llm=fake)
    assert result1["issues_created"] == 1
    assert result1["signals"] >= 3

    issues = (
        await db_session.execute(select(Issue).where(Issue.project_id == test_project.id))
    ).scalars().all()
    assert len(issues) == 1
    issue = issues[0]
    assert issue.title == "Search tool keeps failing"
    assert issue.severity.value == "high"
    assert issue.trace_count == 2  # two distinct failing traces (feedback shares trace 0)
    assert set(issue.signal_types) >= {"explicit_failure", "negative_feedback"}

    # Mark resolved, then a second pass should flip it to recurring (not a new issue).
    issue.status = IssueStatus.resolved
    issue.resolved_at = datetime.now(timezone.utc)
    await db_session.commit()

    result2 = await detect_issues(db_session, test_project.id, llm=fake)
    assert result2["issues_created"] == 0
    assert result2["issues_updated"] == 1

    refreshed = (
        await db_session.execute(select(Issue).where(Issue.project_id == test_project.id))
    ).scalars().all()
    assert len(refreshed) == 1
    assert refreshed[0].status == IssueStatus.recurring
    # Evidence wasn't duplicated on the second pass.
    assert refreshed[0].trace_count == 2


@pytest.mark.asyncio
async def test_detect_issues_no_llm_does_not_duplicate_across_runs(
    db_session, test_project, failing_data
):
    """The deterministic (no-LLM) fallback must merge by fingerprint, not pile up.

    Regression for duplicate "Recurring X failures" issues: running detection
    repeatedly used to create a fresh issue every pass because the fallback
    grouper never matched existing issues.
    """
    first = await detect_issues(db_session, test_project.id, llm=None)
    assert first["issues_created"] >= 1

    before = (
        await db_session.execute(select(Issue).where(Issue.project_id == test_project.id))
    ).scalars().all()
    count_before = len(before)

    # Second pass over the same signals: every group should collapse onto the
    # issue created in the first pass — nothing new, no duplicates.
    second = await detect_issues(db_session, test_project.id, llm=None)
    assert second["issues_created"] == 0
    assert second["issues_updated"] >= 1

    after = (
        await db_session.execute(select(Issue).where(Issue.project_id == test_project.id))
    ).scalars().all()
    assert len(after) == count_before
    # Fingerprints are unique across the surviving issues.
    fps = [i.fingerprint for i in after if i.fingerprint]
    assert len(fps) == len(set(fps))


@pytest.mark.asyncio
async def test_detect_issues_merges_preexisting_duplicates(
    db_session, test_project, test_integration, failing_data
):
    """Legacy duplicates sharing a fingerprint are collapsed on the next pass.

    Seeds three open issues with the same fingerprint (as older builds would
    have produced), each with its own evidence/events, then asserts detection
    folds them into a single survivor that keeps all the evidence.
    """
    from app.models.models import IssueEvent, IssueEvidence, SignalType

    trace_ids = [t.id for t in failing_data["traces"]]
    fp = "eval:faithfulnessToSource"
    seeded: list[Issue] = []
    for n in range(3):
        issue = Issue(
            project_id=test_project.id,
            integration_id=test_integration.id,
            title="Recurring faithfulnessToSource failures",
            category="faithfulnessToSource",
            status=IssueStatus.open,
            signal_types=["eval_failure"],
            fingerprint=fp,
            first_seen_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
            last_seen_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        db_session.add(issue)
        await db_session.flush()
        # Each duplicate references a distinct trace so the survivor accrues both.
        db_session.add(
            IssueEvidence(
                issue_id=issue.id,
                trace_id=trace_ids[n % len(trace_ids)],
                signal_type=SignalType.eval_failure,
                detail=f"dup {n}",
            )
        )
        db_session.add(IssueEvent(issue_id=issue.id, event_type="detected", detail={}))
        seeded.append(issue)
    await db_session.commit()

    result = await detect_issues(db_session, test_project.id, llm=None)
    assert result["issues_merged"] == 2  # 3 dupes -> 1 survivor

    survivors = (
        await db_session.execute(
            select(Issue).where(
                Issue.project_id == test_project.id,
                Issue.fingerprint == fp,
            )
        )
    ).scalars().all()
    assert len(survivors) == 1
    survivor = survivors[0]
    # The oldest issue survived and absorbed the others' distinct-trace evidence.
    assert survivor.id == seeded[0].id
    assert survivor.trace_count == len(set(trace_ids))


# ── API ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_endpoint_and_listing(
    client, test_project, auth_headers, failing_data, monkeypatch
):
    headers = {**auth_headers, "X-Project-Id": str(test_project.id)}

    # Force the no-LLM path so the endpoint test is deterministic and never makes
    # a network call, regardless of whether dev creds happen to be configured.
    from app.routers import issues as issues_router

    def _raise(*args, **kwargs):
        raise issues_router.AnalysisLlmConfigError("no llm in tests")

    monkeypatch.setattr(issues_router, "AnalysisLlmService", _raise)

    resp = await client.post("/api/issues/detect?days=90", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["used_llm"] is False
    assert body["issues_created"] >= 1

    listing = await client.get("/api/issues", headers=headers)
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) >= 1
    issue_id = items[0]["id"]

    detail = await client.get(f"/api/issues/{issue_id}", headers=headers)
    assert detail.status_code == 200
    d = detail.json()
    assert d["evidence"]
    assert any(ev["event_type"] == "detected" for ev in d["events"])

    dismissed = await client.post(f"/api/issues/{issue_id}/dismiss", headers=headers)
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
