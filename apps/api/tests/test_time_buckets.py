"""Tests for the shared day/week/month bucketing.

This is the keystone of the Overview endpoints: it is what lets them aggregate in SQL and
still be tested on SQLite. Every assertion here is guarding a specific way the thing can
silently produce wrong charts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.models.models import Trace, TraceStatus
from app.services.time_buckets import (
    MAX_BUCKETS,
    bucket_axis,
    bucket_end,
    bucket_key,
    date_bucket,
    day_axis,
    normalize_range,
    pct_change,
    previous_window,
    safe_rate,
)

# Deliberate boundary dates. Each one has broken a naive implementation at some point.
WEDNESDAY = datetime(2025, 1, 1, 5, 0, tzinfo=timezone.utc)      # week starts in the prior year
MID_WEEK = datetime(2025, 1, 8, 12, 0, tzinfo=timezone.utc)
SUNDAY = datetime(2025, 1, 12, 23, 30, tzinfo=timezone.utc)      # last day of its ISO week
YEAR_END = datetime(2025, 12, 31, 9, 0, tzinfo=timezone.utc)
LEAP_DAY = datetime(2024, 2, 29, 9, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stamp,bucket,expected",
    [
        (WEDNESDAY, "day", "2025-01-01"),
        (WEDNESDAY, "week", "2024-12-30"),   # ISO week crosses the year boundary
        (WEDNESDAY, "month", "2025-01-01"),
        (SUNDAY, "day", "2025-01-12"),
        (SUNDAY, "week", "2025-01-06"),      # Sunday belongs to the week that began Monday
        (MID_WEEK, "week", "2025-01-06"),
        (YEAR_END, "week", "2025-12-29"),
        (YEAR_END, "month", "2025-12-01"),
        (LEAP_DAY, "day", "2024-02-29"),
        (LEAP_DAY, "week", "2024-02-26"),
        (LEAP_DAY, "month", "2024-02-01"),
    ],
)
def test_bucket_key_boundaries(stamp, bucket, expected):
    assert bucket_key(stamp, bucket) == expected


def test_bucket_key_accepts_naive_datetime_as_utc():
    assert bucket_key(datetime(2025, 1, 12, 23, 30), "week") == "2025-01-06"


def test_bucket_axis_day_is_inclusive_of_both_ends():
    axis = bucket_axis(
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        datetime(2025, 1, 3, tzinfo=timezone.utc),
        "day",
    )
    assert axis == ["2025-01-01", "2025-01-02", "2025-01-03"]


def test_bucket_axis_week_spans_year_boundary():
    axis = bucket_axis(
        datetime(2025, 12, 20, tzinfo=timezone.utc),
        datetime(2026, 1, 5, tzinfo=timezone.utc),
        "week",
    )
    assert axis == ["2025-12-15", "2025-12-22", "2025-12-29", "2026-01-05"]


def test_bucket_axis_month_rolls_the_year():
    axis = bucket_axis(
        datetime(2025, 11, 15, tzinfo=timezone.utc),
        datetime(2026, 2, 2, tzinfo=timezone.utc),
        "month",
    )
    assert axis == ["2025-11-01", "2025-12-01", "2026-01-01", "2026-02-01"]


def test_bucket_axis_single_instant_gives_one_bucket():
    axis = bucket_axis(WEDNESDAY, WEDNESDAY, "month")
    assert axis == ["2025-01-01"]


def test_bucket_axis_reversed_range_is_empty():
    assert bucket_axis(MID_WEEK, WEDNESDAY, "day") == []


def test_bucket_axis_stops_just_past_the_cap():
    """The axis must not grow without bound; the router turns this into a 422."""
    axis = bucket_axis(
        datetime(2020, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        "day",
    )
    assert len(axis) == MAX_BUCKETS + 1


@pytest.mark.parametrize(
    "label,bucket,expected",
    [
        ("2025-01-06", "day", datetime(2025, 1, 7, tzinfo=timezone.utc)),
        ("2025-01-06", "week", datetime(2025, 1, 13, tzinfo=timezone.utc)),
        ("2025-12-01", "month", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ("2024-02-01", "month", datetime(2024, 3, 1, tzinfo=timezone.utc)),
    ],
)
def test_bucket_end_is_exclusive(label, bucket, expected):
    assert bucket_end(label, bucket) == expected


def test_day_axis_covers_the_rolling_lookback():
    axis = day_axis(
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        datetime(2025, 1, 4, tzinfo=timezone.utc),
    )
    assert axis == ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"]


def test_pct_change_returns_none_without_a_baseline():
    # Not 0.0 and not 1.0: a zero baseline has no meaningful percentage, and inventing
    # one would render a fake delta arrow.
    assert pct_change(5, 0) is None
    assert pct_change(None, 10) is None
    assert pct_change(5, None) is None


def test_pct_change_signs():
    assert pct_change(150, 100) == 0.5
    assert pct_change(50, 100) == -0.5
    assert pct_change(100, 100) == 0.0


def test_safe_rate_handles_empty_denominator():
    assert safe_rate(0, 0) == 0.0
    assert safe_rate(9, 10) == 0.9


def test_previous_window_is_the_equal_length_window_before():
    start = datetime(2025, 1, 8, tzinfo=timezone.utc)
    end = datetime(2025, 1, 15, tzinfo=timezone.utc)
    prev_start, prev_end = previous_window(start, end)
    assert prev_end == start
    assert prev_start == datetime(2025, 1, 1, tzinfo=timezone.utc)


def test_normalize_range_prefers_explicit_start_over_days():
    start, end = normalize_range(
        7, datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 5, tzinfo=timezone.utc)
    )
    assert (start.isoformat(), end.isoformat()) == (
        "2025-01-01T00:00:00+00:00",
        "2025-01-05T00:00:00+00:00",
    )


def test_normalize_range_days_only_ends_now():
    start, end = normalize_range(7, None, None)
    assert (end - start).days == 7
    assert end.tzinfo is not None


def test_date_bucket_rejects_an_unknown_bucket():
    with pytest.raises(ValueError):
        date_bucket(Trace.start_time, "quarter")


# ---------------------------------------------------------------------------
# Dialect behaviour — the reason this module exists
# ---------------------------------------------------------------------------


async def _seed(db_session, integration, stamps):
    for i, ts in enumerate(stamps):
        db_session.add(
            Trace(
                id=uuid4(), integration_id=integration.id, external_id=f"tb-{i}",
                name="chat", start_time=ts, status=TraceStatus.success, user_id=f"u{i}",
            )
        )
    await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bucket,expected",
    [
        ("day", {"2024-02-29": 1, "2025-01-01": 1, "2025-01-08": 1, "2025-01-12": 1}),
        ("week", {"2024-02-26": 1, "2024-12-30": 1, "2025-01-06": 2}),
        ("month", {"2024-02-01": 1, "2025-01-01": 3}),
    ],
)
async def test_date_bucket_groups_correctly_in_sql(
    db_session, test_integration, bucket, expected
):
    """The SQL expression must agree with bucket_key on every granularity.

    Executed against the real (SQLite) test database, which is exactly what
    ``cast(col, Date)`` cannot do.
    """
    await _seed(db_session, test_integration, [WEDNESDAY, MID_WEEK, SUNDAY, LEAP_DAY])
    label = date_bucket(Trace.start_time, bucket).label("bucket")
    rows = (
        await db_session.execute(
            select(label, func.count(Trace.id)).group_by(label).order_by(label)
        )
    ).all()
    assert {r.bucket: r[1] for r in rows} == expected


@pytest.mark.asyncio
async def test_date_bucket_matches_python_bucket_key(db_session, test_integration):
    """Guards against the SQL and Python paths drifting apart."""
    stamps = [WEDNESDAY, MID_WEEK, SUNDAY, YEAR_END, LEAP_DAY]
    await _seed(db_session, test_integration, stamps)
    for bucket in ("day", "week", "month"):
        label = date_bucket(Trace.start_time, bucket).label("bucket")
        sql_labels = sorted(
            r.bucket for r in (await db_session.execute(select(label))).all()
        )
        assert sql_labels == sorted(bucket_key(s, bucket) for s in stamps), bucket


@pytest.mark.asyncio
async def test_bucket_is_part_of_the_statement_cache_key(db_session, test_integration):
    """A week query must not reuse the SQL compiled for an earlier day query.

    SQLAlchemy caches compiled statements, and `bucket` is not part of the generated
    cache key, so `inherit_cache = True` on date_bucket makes the second query silently
    return the first one's granularity. That bug produces daily labels on a chart the
    user asked to see monthly, with no error anywhere.
    """
    await _seed(db_session, test_integration, [WEDNESDAY, MID_WEEK, SUNDAY])

    day_col = date_bucket(Trace.start_time, "day").label("bucket")
    day_labels = sorted(
        r.bucket for r in (await db_session.execute(select(day_col).group_by(day_col))).all()
    )
    week_col = date_bucket(Trace.start_time, "week").label("bucket")
    week_labels = sorted(
        r.bucket for r in (await db_session.execute(select(week_col).group_by(week_col))).all()
    )
    month_col = date_bucket(Trace.start_time, "month").label("bucket")
    month_labels = sorted(
        r.bucket for r in (await db_session.execute(select(month_col).group_by(month_col))).all()
    )

    assert day_labels == ["2025-01-01", "2025-01-08", "2025-01-12"]
    assert week_labels == ["2024-12-30", "2025-01-06"]
    assert month_labels == ["2025-01-01"]


@pytest.mark.parametrize("bucket", ["day", "week", "month"])
def test_postgres_branch_compiles_to_date_trunc(bucket):
    """Coverage for the branch the SQLite test suite can never execute.

    Verified against a real PostgreSQL 16 server during development: it agrees with the
    SQLite branch on every boundary date above, including the leap day and the ISO week
    that starts in the previous year.
    """
    sql = str(
        select(date_bucket(Trace.start_time, bucket)).compile(dialect=postgresql.dialect())
    )
    assert f"date_trunc('{bucket}'" in sql
    # Without the explicit zone the truncation would follow the server's TimeZone setting.
    assert "AT TIME ZONE 'UTC'" in sql
    assert "'YYYY-MM-DD'" in sql
