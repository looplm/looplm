"""Day/week/month time bucketing shared by the Overview endpoints.

Every other bucketed endpoint in this codebase uses ``cast(col, Date)`` (see
``routers/dashboard.py``, ``routers/llm_costs.py``, ``services/feedback_stats_service.py``).
That expression *raises* on the SQLite test database: SQLite gives ``CAST(x AS DATE)``
NUMERIC affinity, so it returns a year integer and SQLAlchemy's ``Date`` result
processor fails with ``fromisoformat: argument must be str``. That is why
``tests/test_dashboard_metrics.py`` can only unit-test pure helpers and never calls
``/api/dashboard/stats`` end to end.

``date_bucket`` avoids the tradeoff. It is a dialect-dispatched SQL expression that
compiles to ``date_trunc`` on PostgreSQL and ``strftime`` on SQLite, so bucketing
stays a ``GROUP BY`` aggregate in the database (rows returned == number of buckets,
not number of traces) *and* the endpoints are testable end to end. The alternative
used by ``routers/analytics.py`` — pulling every row and bucketing in Python — is
fine there because that endpoint already needs the row payloads, but it does not
scale for plain counts.

Conventions: everything is UTC, week starts Monday (ISO 8601), and a bucket is
labelled by its start date as ``YYYY-MM-DD``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal, get_args

from sqlalchemy import String
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

Bucket = Literal["day", "week", "month"]

BUCKETS: tuple[Bucket, ...] = get_args(Bucket)

# A bucket count above this is refused rather than silently coarsened, so the
# frontend's bucket toggle never lies about what it is showing.
MAX_BUCKETS = 400

# Rolling-window widths for the DAU/WAU/MAU triple.
DAU_DAYS = 1
WAU_DAYS = 7
MAU_DAYS = 30


class date_bucket(FunctionElement):  # noqa: N801 — SQL function elements are lowercase by convention
    """Truncate a tz-aware timestamp column to its UTC bucket-start label.

    Renders as a ``YYYY-MM-DD`` string on every dialect so the value can be grouped,
    ordered and returned as-is without a dialect-specific result processor.
    """

    type = String()

    # `bucket` is NOT part of SQLAlchemy's compiled-statement cache key, so inheriting
    # the cache makes a `week` query reuse the SQL compiled for an earlier `day` query
    # in the same session: every chart silently renders daily labels. Do not set this
    # to True without adding `bucket` to the cache key.
    inherit_cache = False

    def __init__(self, col, bucket: Bucket) -> None:
        if bucket not in BUCKETS:
            raise ValueError(f"unsupported bucket {bucket!r}, expected one of {BUCKETS}")
        # Validated here as well as by FastAPI, because the value is interpolated into
        # SQL below and a future internal caller must not be able to smuggle anything in.
        self.bucket: Bucket = bucket
        super().__init__(col)


@compiles(date_bucket, "postgresql")
def _compile_date_bucket_pg(element: date_bucket, compiler, **kw) -> str:
    col = compiler.process(list(element.clauses)[0], **kw)
    # `AT TIME ZONE 'UTC'` makes the truncation independent of the server's TimeZone GUC.
    return f"to_char(date_trunc('{element.bucket}', ({col}) AT TIME ZONE 'UTC'), 'YYYY-MM-DD')"


@compiles(date_bucket)
def _compile_date_bucket_default(element: date_bucket, compiler, **kw) -> str:
    """Generic branch, which in this codebase means the SQLite test database."""
    col = compiler.process(list(element.clauses)[0], **kw)
    if element.bucket == "week":
        # Back up 6 days, then advance to the next Monday. For a Monday input that
        # lands back on itself; for a Sunday it lands on the Monday 6 days earlier.
        # Equivalent to ISO week start, which is what date_trunc('week') does on PG.
        return f"strftime('%Y-%m-%d', {col}, '-6 days', 'weekday 1')"
    if element.bucket == "month":
        return f"strftime('%Y-%m-01', {col})"
    return f"strftime('%Y-%m-%d', {col})"


def ensure_utc(dt: datetime) -> datetime:
    """Attach UTC to a naive datetime; convert an aware one."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def bucket_start(d: date, bucket: Bucket) -> date:
    """The first day of the bucket containing ``d``."""
    if bucket == "week":
        return d - timedelta(days=d.weekday())
    if bucket == "month":
        return d.replace(day=1)
    return d


def bucket_key(dt: datetime, bucket: Bucket) -> str:
    """Python equivalent of the SQL ``date_bucket`` label, for post-query bucketing."""
    return bucket_start(ensure_utc(dt).date(), bucket).isoformat()


def next_bucket_start(d: date, bucket: Bucket) -> date:
    if bucket == "week":
        return d + timedelta(days=7)
    if bucket == "month":
        return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
    return d + timedelta(days=1)


def bucket_end(label: str, bucket: Bucket) -> datetime:
    """Exclusive UTC end of the bucket that ``label`` starts."""
    start = date.fromisoformat(label)
    return datetime.combine(
        next_bucket_start(start, bucket), datetime.min.time(), tzinfo=timezone.utc
    )


def bucket_axis(start: datetime, end: datetime, bucket: Bucket) -> list[str]:
    """Every bucket label from ``start`` to ``end`` inclusive, in order.

    Buckets with no rows are filled from this axis rather than in SQL, so a gap in the
    data becomes an explicit zero (or null) point instead of a missing column.
    """
    if end < start:
        return []
    cursor = bucket_start(ensure_utc(start).date(), bucket)
    last = bucket_start(ensure_utc(end).date(), bucket)
    labels: list[str] = []
    while cursor <= last:
        labels.append(cursor.isoformat())
        cursor = next_bucket_start(cursor, bucket)
        if len(labels) > MAX_BUCKETS:
            break
    return labels


def bucket_count(start: datetime, end: datetime, bucket: Bucket) -> int:
    """Number of buckets the range spans, without materializing the axis."""
    return len(bucket_axis(start, end, bucket))


def day_axis(start: datetime, end: datetime) -> list[str]:
    """Every day label in the range, used for the rolling-window activity matrix."""
    cursor = ensure_utc(start).date()
    last = ensure_utc(end).date()
    out: list[str] = []
    while cursor <= last:
        out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def normalize_range(
    days: int, start_date: datetime | None, end_date: datetime | None
) -> tuple[datetime, datetime]:
    """Resolve the (days | start_date | end_date) param trio into a UTC window.

    Same precedence as ``routers/dashboard.py`` and ``routers/costs_overview.py``:
    an explicit start wins over ``days``, and a missing end means now.
    """
    now = datetime.now(timezone.utc)
    end = ensure_utc(end_date) if end_date else now
    if start_date:
        return ensure_utc(start_date), end
    return end - timedelta(days=days), end


def previous_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """The equally-long window immediately before ``[start, end]``.

    Matches the comparison the dashboard already shows, so the two pages agree on what
    "vs previous period" means.
    """
    span = end - start
    return start - span, start


def pct_change(current: float | None, previous: float | None) -> float | None:
    """Relative change, or None when there is no usable baseline.

    Returning None rather than 0.0 or 1.0 for a zero baseline is deliberate: the UI
    renders nothing at all instead of a fabricated delta. Same convention as
    ``dashboard._regression_flag``.
    """
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous, 4)


def safe_rate(numerator: float, denominator: float, digits: int = 4) -> float:
    """Ratio that degrades to 0.0 on an empty denominator."""
    if not denominator:
        return 0.0
    return round(numerator / denominator, digits)
