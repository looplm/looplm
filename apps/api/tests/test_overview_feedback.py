"""Tests for the feedback section of GET /api/overview/summary.

These run end to end against the API, which the equivalent dashboard tests cannot do
(see tests/test_dashboard_metrics.py) because ``cast(col, Date)`` breaks on SQLite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.models import FeedbackScore, Trace, TraceStatus

# Three calendar weeks so week bucketing has something to collapse.
W1 = datetime(2025, 1, 6, 10, 0, tzinfo=timezone.utc)   # Monday, week 2025-01-06
W1B = datetime(2025, 1, 8, 10, 0, tzinfo=timezone.utc)  # same week
W3 = datetime(2025, 1, 20, 10, 0, tzinfo=timezone.utc)  # week 2025-01-20, leaving W2 empty

RANGE = {"start_date": "2025-01-06T00:00:00+00:00", "end_date": "2025-01-26T00:00:00+00:00"}


@pytest.fixture
def headers(auth_headers, test_project):
    return {**auth_headers, "X-Project-Id": str(test_project.id)}


def _trace(integration_id, ext, stamp, *, user_id="alice", environment=None):
    return Trace(
        id=uuid4(), integration_id=integration_id, external_id=ext, name="chat",
        start_time=stamp, status=TraceStatus.success, user_id=user_id,
        trace_metadata={"environment": environment} if environment else {},
    )


def _score(integration_id, trace_id, ext, value, stamp, name="user-feedback"):
    return FeedbackScore(
        id=uuid4(), integration_id=integration_id, trace_id=trace_id,
        external_id=ext, external_trace_id=ext, score_name=name, value=value,
        scored_at=stamp,
    )


@pytest_asyncio.fixture
async def seeded(db_session, test_integration):
    """Week 1: 2 positive + 1 negative. Week 3: 1 negative. Week 2: nothing."""
    t1 = _trace(test_integration.id, "f1", W1)
    t2 = _trace(test_integration.id, "f2", W1B)
    t3 = _trace(test_integration.id, "f3", W3)
    db_session.add_all([t1, t2, t3])
    await db_session.flush()
    db_session.add_all([
        _score(test_integration.id, t1.id, "s1", 1.0, W1),
        _score(test_integration.id, t2.id, "s2", 1.0, W1B),
        _score(test_integration.id, t2.id, "s3", 0.0, W1B),
        _score(test_integration.id, t3.id, "s4", 0.0, W3),
        # A grader score, not end-user sentiment. Must not be counted.
        _score(test_integration.id, t1.id, "s5", 0.0, W1, name="faithfulness"),
    ])
    await db_session.commit()
    return t1, t2, t3


@pytest.mark.asyncio
async def test_daily_buckets_and_totals(client, headers, seeded):
    r = await client.get("/api/overview/summary", params={"bucket": "day", **RANGE}, headers=headers)
    assert r.status_code == 200, r.text
    fb = r.json()["feedback"]

    assert fb["totals"] == {
        "total": 4,
        "positive": 2,
        "negative": 2,
        "positive_rate": 0.5,
        "traces_with_feedback": 3,
    }
    by_bucket = {p["bucket"]: p for p in fb["points"]}
    assert by_bucket["2025-01-06"]["positive"] == 1
    assert by_bucket["2025-01-08"]["positive"] == 1
    assert by_bucket["2025-01-08"]["negative"] == 1
    assert by_bucket["2025-01-20"]["negative"] == 1


@pytest.mark.asyncio
async def test_empty_buckets_are_zero_filled(client, headers, seeded):
    """A day with no feedback still gets a column, so the axis has no holes."""
    r = await client.get("/api/overview/summary", params={"bucket": "day", **RANGE}, headers=headers)
    points = r.json()["feedback"]["points"]
    # 2025-01-06 through 2025-01-26 inclusive.
    assert len(points) == 21
    quiet = next(p for p in points if p["bucket"] == "2025-01-07")
    assert (quiet["total"], quiet["positive"], quiet["negative"]) == (0, 0, 0)
    assert quiet["positive_rate"] == 0.0


@pytest.mark.asyncio
async def test_week_bucketing_collapses_the_first_week(client, headers, seeded):
    r = await client.get("/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers)
    points = {p["bucket"]: p for p in r.json()["feedback"]["points"]}
    assert set(points) == {"2025-01-06", "2025-01-13", "2025-01-20"}
    assert points["2025-01-06"]["total"] == 3
    assert points["2025-01-06"]["positive"] == 2
    assert points["2025-01-13"]["total"] == 0
    assert points["2025-01-20"]["negative"] == 1


@pytest.mark.asyncio
async def test_month_bucketing(client, headers, seeded):
    r = await client.get("/api/overview/summary", params={"bucket": "month", **RANGE}, headers=headers)
    points = r.json()["feedback"]["points"]
    assert len(points) == 1
    assert points[0]["bucket"] == "2025-01-01"
    assert points[0]["total"] == 4


@pytest.mark.asyncio
async def test_grader_scores_are_excluded(client, headers, seeded):
    """Only score_name == 'user-feedback' is end-user sentiment."""
    r = await client.get("/api/overview/summary", params={"bucket": "day", **RANGE}, headers=headers)
    # 5 scores were seeded; the faithfulness one must not appear.
    assert r.json()["feedback"]["totals"]["total"] == 4


@pytest.mark.asyncio
async def test_environment_filter_applies(client, db_session, test_integration, headers):
    t_prod = _trace(test_integration.id, "e1", W1, environment="prod")
    t_dev = _trace(test_integration.id, "e2", W1, environment="dev")
    db_session.add_all([t_prod, t_dev])
    await db_session.flush()
    db_session.add_all([
        _score(test_integration.id, t_prod.id, "es1", 1.0, W1),
        _score(test_integration.id, t_dev.id, "es2", 0.0, W1),
    ])
    await db_session.commit()

    r = await client.get(
        "/api/overview/summary",
        params={"bucket": "day", "environment": "prod", **RANGE},
        headers=headers,
    )
    totals = r.json()["feedback"]["totals"]
    assert (totals["total"], totals["positive"], totals["negative"]) == (1, 1, 0)


@pytest.mark.asyncio
async def test_exclude_user_ids_keeps_anonymous_traffic(
    client, db_session, test_integration, headers
):
    """Excluding a user must not also drop traces with no user_id.

    SQL evaluates ``NULL NOT IN (...)`` to NULL, so a bare NOT IN would silently hide all
    anonymous traffic. This is the whole reason services/user_filter.py exists.
    """
    t_staff = _trace(test_integration.id, "x1", W1, user_id="staff")
    t_anon = _trace(test_integration.id, "x2", W1, user_id=None)
    db_session.add_all([t_staff, t_anon])
    await db_session.flush()
    db_session.add_all([
        _score(test_integration.id, t_staff.id, "xs1", 1.0, W1),
        _score(test_integration.id, t_anon.id, "xs2", 0.0, W1),
    ])
    await db_session.commit()

    r = await client.get(
        "/api/overview/summary",
        params={"bucket": "day", "exclude_user_ids": ["staff"], **RANGE},
        headers=headers,
    )
    totals = r.json()["feedback"]["totals"]
    assert totals["total"] == 1, "the anonymous trace's feedback should survive"
    assert totals["negative"] == 1


@pytest.mark.asyncio
async def test_other_projects_are_not_counted(
    client, db_session, test_user, test_integration, headers
):
    from app.models.models import Integration, IntegrationType
    from app.models.project import Project

    other_project = Project(id=uuid4(), owner_id=test_user.id, name="Other")
    db_session.add(other_project)
    await db_session.flush()
    other_integration = Integration(
        id=uuid4(), project_id=other_project.id, type=IntegrationType.langfuse,
        name="other", api_key=b"k", base_url="https://x",
    )
    db_session.add(other_integration)
    await db_session.flush()
    t = _trace(other_integration.id, "o1", W1)
    db_session.add(t)
    await db_session.flush()
    db_session.add(_score(other_integration.id, t.id, "os1", 1.0, W1))
    await db_session.commit()

    r = await client.get("/api/overview/summary", params={"bucket": "day", **RANGE}, headers=headers)
    assert r.json()["feedback"]["totals"]["total"] == 0


@pytest.mark.asyncio
async def test_kpi_carries_the_feedback_rate(client, headers, seeded):
    r = await client.get("/api/overview/summary", params={"bucket": "day", **RANGE}, headers=headers)
    kpi = next(k for k in r.json()["kpis"] if k["key"] == "feedback_rate")
    assert kpi["value"] == 0.5
    assert kpi["unit"] == "rate"
    # The previous window has no feedback at all, so there is no comparable baseline and
    # the UI must render no delta rather than a fabricated one.
    assert kpi["previous"] is None
    assert kpi["change_pct"] is None


@pytest.mark.asyncio
async def test_too_many_buckets_is_refused(client, headers):
    r = await client.get(
        "/api/overview/summary",
        params={"bucket": "day", "start_date": "2020-01-01T00:00:00+00:00",
                "end_date": "2026-01-01T00:00:00+00:00"},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error"]["code"] == "RANGE_TOO_LARGE"
