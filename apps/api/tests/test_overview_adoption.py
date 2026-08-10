"""Tests for the adoption section of GET /api/overview/summary.

The subtle logic (new vs returning across the window boundary, the cumulative baseline,
rolling windows) is unit-tested directly against the pure helpers, then checked once more
end to end so the query wiring is covered too.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.models import Trace, TraceStatus
from app.services.overview_adoption_math import (
    bucket_active_users,
    cumulative_unique,
    rolling_active,
    split_new_returning,
    stickiness,
)

# Outside the selected window but inside the 13-day comparison window before it
# (2024-12-24 to 2025-01-06), so it serves as both the "returning user" history and the
# previous-period baseline.
BEFORE = datetime(2024, 12, 28, 10, 0, tzinfo=timezone.utc)
W1 = datetime(2025, 1, 6, 10, 0, tzinfo=timezone.utc)        # Monday
W1B = datetime(2025, 1, 7, 10, 0, tzinfo=timezone.utc)
W2 = datetime(2025, 1, 13, 10, 0, tzinfo=timezone.utc)       # Monday, next week

RANGE = {"start_date": "2025-01-06T00:00:00+00:00", "end_date": "2025-01-19T00:00:00+00:00"}


@pytest.fixture
def headers(auth_headers, test_project):
    return {**auth_headers, "X-Project-Id": str(test_project.id)}


# ---------------------------------------------------------------------------
# Pure math
# ---------------------------------------------------------------------------


def test_bucket_active_users_rolls_days_into_weeks():
    activity = {
        "2025-01-06": {"a", "b"},
        "2025-01-07": {"a"},
        "2025-01-13": {"c"},
        # Outside the axis; must be dropped rather than crashing or leaking in.
        "2025-02-01": {"z"},
    }
    rolled = bucket_active_users(activity, ["2025-01-06", "2025-01-13"], "week")
    assert rolled["2025-01-06"] == {"a", "b"}
    assert rolled["2025-01-13"] == {"c"}


def test_split_new_returning_uses_first_ever_activity():
    first_seen = {"old": "2024-12-16", "fresh": "2025-01-06"}
    new, returning = split_new_returning({"old", "fresh"}, first_seen, "2025-01-06")
    # `old` was first seen before the window, so it is returning even though this is its
    # first bucket in view. That correctness depends on the first-seen query being
    # unbounded in time.
    assert (new, returning) == (1, 1)


def test_split_new_returning_counts_unknown_users_as_returning():
    new, returning = split_new_returning({"ghost"}, {}, "2025-01-06")
    assert (new, returning) == (0, 1)


def test_cumulative_unique_continues_from_the_baseline():
    axis = ["2025-01-06", "2025-01-13", "2025-01-20"]
    first_seen = {"a": "2025-01-06", "b": "2025-01-06", "c": "2025-01-20"}
    # 10 users existed before the window opened.
    assert cumulative_unique(first_seen, axis, baseline=10) == [12, 12, 13]


def test_cumulative_unique_is_monotonic_with_no_baseline():
    axis = ["2025-01-06", "2025-01-13"]
    assert cumulative_unique({"a": "2025-01-13"}, axis, baseline=0) == [0, 1]


def test_cumulative_unique_ignores_first_seen_outside_the_axis():
    axis = ["2025-01-13"]
    assert cumulative_unique({"a": "2025-01-06"}, axis, baseline=5) == [5]


def test_rolling_active_counts_distinct_users_in_the_window():
    activity = {
        "2025-01-10": {"a"},
        "2025-01-12": {"a", "b"},
        "2025-01-13": {"c"},
        "2025-01-02": {"d"},  # 11 days back, outside a 7-day window
    }
    at = date(2025, 1, 13)
    assert rolling_active(activity, at, 1) == 1          # just c
    assert rolling_active(activity, at, 7) == 3          # a, b, c
    assert rolling_active(activity, at, 30) == 4         # plus d


def test_rolling_active_on_an_empty_matrix():
    assert rolling_active({}, date(2025, 1, 13), 7) == 0


def test_stickiness_is_none_without_monthly_activity():
    # Not 0.0 — an undefined ratio rendered as 0% reads as a collapse in engagement.
    assert stickiness(0, 0) is None
    assert stickiness(5, 0) is None
    assert stickiness(None, None) is None


def test_stickiness_ratio():
    assert stickiness(5, 20) == 0.25


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


def _trace(integration_id, ext, stamp, user_id, thread_id="t1"):
    return Trace(
        id=uuid4(), integration_id=integration_id, external_id=ext, name="chat",
        start_time=stamp, status=TraceStatus.success, user_id=user_id, thread_id=thread_id,
    )


@pytest_asyncio.fixture
async def seeded(db_session, test_integration):
    """`old` predates the window; `fresh` starts in week 1; one anonymous trace."""
    db_session.add_all([
        _trace(test_integration.id, "a0", BEFORE, "old", thread_id="th-old"),
        _trace(test_integration.id, "a1", W1, "old", thread_id="th-1"),
        _trace(test_integration.id, "a2", W1, "fresh", thread_id="th-2"),
        _trace(test_integration.id, "a3", W1B, "fresh", thread_id="th-2"),
        _trace(test_integration.id, "a4", W2, "old", thread_id="th-3"),
        _trace(test_integration.id, "a5", W1, None, thread_id="th-4"),
    ])
    await db_session.commit()


@pytest.mark.asyncio
async def test_new_vs_returning_across_the_window_boundary(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    assert r.status_code == 200, r.text
    points = {p["bucket"]: p for p in r.json()["adoption"]["points"]}

    week1 = points["2025-01-06"]
    assert week1["active_users"] == 2
    # `fresh` is new here; `old` was active in December so it is returning.
    assert week1["new_users"] == 1
    assert week1["returning_users"] == 1

    week2 = points["2025-01-13"]
    assert week2["active_users"] == 1
    assert week2["new_users"] == 0
    assert week2["returning_users"] == 1


@pytest.mark.asyncio
async def test_cumulative_users_includes_pre_window_history(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    points = r.json()["adoption"]["points"]
    # `old` is the baseline, `fresh` joins in week 1, nobody new in week 2.
    assert [p["cumulative_users"] for p in points] == [2, 2]
    assert r.json()["adoption"]["totals"]["cumulative_users"] == 2


@pytest.mark.asyncio
async def test_anonymous_traces_count_as_volume_but_not_as_users(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    totals = r.json()["adoption"]["totals"]
    # 5 traces inside the window, 4 of them attributed to a user.
    assert totals["traces"] == 5
    assert totals["traces_attributed"] == 4
    assert totals["active_users"] == 2
    # Per-user average divides the attributed traces only; anonymous traffic has no user.
    assert totals["avg_traces_per_active_user"] == 2.0


@pytest.mark.asyncio
async def test_threads_are_counted_distinctly(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    # th-1, th-2 (twice), th-3, th-4 inside the window.
    assert r.json()["adoption"]["totals"]["threads"] == 4


@pytest.mark.asyncio
async def test_rolling_metrics_are_present_at_window_end(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    adoption = r.json()["adoption"]
    assert adoption["rolling_available"] is True
    totals = adoption["totals"]
    # Window ends 2025-01-19; the last activity is 2025-01-13 (`old`).
    assert totals["dau"] == 0            # nothing on the final day
    assert totals["wau"] == 1            # `old` on the 13th
    assert totals["mau"] == 2            # `old` and `fresh`
    assert totals["stickiness"] == 0.0


@pytest.mark.asyncio
async def test_growth_compares_against_the_previous_window(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    growth = r.json()["adoption"]["growth"]
    # The preceding equal-length window (2024-12-24 to 2025-01-06) holds only the
    # December trace from `old`.
    assert growth["traces"]["current"] == 5
    assert growth["traces"]["previous"] == 1
    assert growth["traces"]["change_pct"] == 4.0
    assert growth["active_users"]["previous"] == 1


@pytest.mark.asyncio
async def test_growth_delta_is_none_without_a_baseline(client, headers, db_session, test_integration):
    db_session.add(_trace(test_integration.id, "solo", W1, "someone"))
    await db_session.commit()
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    growth = r.json()["adoption"]["growth"]
    assert growth["traces"]["previous"] == 0
    assert growth["traces"]["change_pct"] is None


@pytest.mark.asyncio
async def test_active_users_kpi(client, headers, seeded):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "week", **RANGE}, headers=headers
    )
    kpi = next(k for k in r.json()["kpis"] if k["key"] == "active_users")
    assert kpi["value"] == 2.0
    assert kpi["unit"] == "count"
    assert kpi["sub"] == "1 new, 1 returning"
    assert kpi["series"] == [2.0, 1.0]


@pytest.mark.asyncio
async def test_empty_project_returns_zeros_not_an_error(client, headers):
    r = await client.get(
        "/api/overview/summary", params={"bucket": "day", **RANGE}, headers=headers
    )
    assert r.status_code == 200
    totals = r.json()["adoption"]["totals"]
    assert (totals["active_users"], totals["traces"], totals["cumulative_users"]) == (0, 0, 0)
    assert totals["stickiness"] is None
