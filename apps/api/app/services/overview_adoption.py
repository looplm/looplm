"""User adoption and usage growth.

Three queries feed this section:

A. A user-day activity matrix, pre-rolled 29 days before the window so MAU is defined at
   the very first bucket. Its cardinality is ``distinct_users x active_days``, not
   ``traces``, which is why pulling rows here is acceptable where it would not be for
   plain counts.
B. First-seen per user with **no time bound**, restricted to users active in the window.
   This is what makes new-vs-returning correct across the window boundary. Restricting by
   ``user_id IN (window-active)`` lets PostgreSQL drive from the existing partial index
   ``idx_traces_user_id`` instead of scanning the project's whole trace history.
C. Per-bucket volume, a plain grouped aggregate.

No first-seen cache table: maintaining one would put a write on the hot path in
``services/trace_persistence.py`` and needs backfill plus delete semantics, for a query
that is currently sub-millisecond.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Trace
from app.models.project import Project
from app.schemas.overview_common import Delta
from app.schemas.overview_summary import (
    AdoptionBucketPoint,
    AdoptionGrowth,
    AdoptionOverview,
    AdoptionTotals,
)
from app.services.overview_adoption_math import (
    bucket_active_users,
    cumulative_unique,
    rolling_active,
    split_new_returning,
    stickiness,
)
from app.services.time_buckets import (
    DAU_DAYS,
    MAU_DAYS,
    WAU_DAYS,
    Bucket,
    bucket_end,
    bucket_key,
    date_bucket,
    ensure_utc,
    pct_change,
    safe_rate,
)
from app.services.trace_scope import trace_scope_filters

# Above this many (user, day) pairs the rolling metrics are skipped rather than risking
# the API process's memory. The section still returns everything else.
MAX_ACTIVITY_ROWS = 250_000


async def _activity_matrix(
    db: AsyncSession,
    project: Project,
    *,
    start: datetime,
    end: datetime,
    filters: dict,
) -> tuple[dict[str, set[str]], bool]:
    """Query A. Returns (day -> users, rolling_available)."""
    lookback = start - timedelta(days=MAU_DAYS - 1)
    day_label = date_bucket(Trace.start_time, "day").label("day")
    scope = trace_scope_filters(project, start=lookback, end=end, **filters)
    rows = (
        await db.execute(
            select(day_label, Trace.user_id)
            .where(*scope, Trace.user_id.isnot(None))
            .group_by(day_label, Trace.user_id)
        )
    ).all()
    if len(rows) > MAX_ACTIVITY_ROWS:
        return {}, False
    activity: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        activity[str(r.day)].add(r.user_id)
    return activity, True


async def _first_seen(
    db: AsyncSession,
    project: Project,
    *,
    start: datetime,
    end: datetime,
    bucket: Bucket,
    filters: dict,
) -> dict[str, str]:
    """Query B. user_id -> bucket label of their first-ever activity.

    First-seen honors the same environment/user/trace-name filters as the window, so with
    an environment selected "new" means new *to that environment*. Consistent with every
    other number on the page.
    """
    window_users = (
        select(Trace.user_id)
        .where(
            *trace_scope_filters(project, start=start, end=end, **filters),
            Trace.user_id.isnot(None),
        )
        .group_by(Trace.user_id)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(Trace.user_id, func.min(Trace.start_time).label("first_seen"))
            .where(
                *trace_scope_filters(project, **filters),
                Trace.user_id.isnot(None),
                Trace.user_id.in_(window_users),
            )
            .group_by(Trace.user_id)
        )
    ).all()
    out: dict[str, str] = {}
    for r in rows:
        if r.first_seen is None:
            continue
        stamp = r.first_seen
        if isinstance(stamp, str):  # SQLite hands back strings for some paths
            stamp = datetime.fromisoformat(stamp)
        out[r.user_id] = bucket_key(stamp, bucket)
    return out


async def _baseline_users(
    db: AsyncSession, project: Project, *, start: datetime, filters: dict
) -> int:
    """Distinct users who appeared strictly before the window, for the cumulative curve."""
    scope = trace_scope_filters(project, **filters)
    row = (
        await db.execute(
            select(func.count(func.distinct(Trace.user_id))).where(
                *scope, Trace.user_id.isnot(None), Trace.start_time < start
            )
        )
    ).scalar()
    return int(row or 0)


async def _volume(
    db: AsyncSession,
    project: Project,
    *,
    start: datetime,
    end: datetime,
    bucket: Bucket,
    filters: dict,
) -> dict[str, tuple[int, int, int, int]]:
    """Query C. bucket -> (traces, traces_attributed, threads, active_users)."""
    label = date_bucket(Trace.start_time, bucket).label("bucket")
    rows = (
        await db.execute(
            select(
                label,
                func.count(Trace.id).label("traces"),
                func.sum(case((Trace.user_id.isnot(None), 1), else_=0)).label("attributed"),
                func.count(func.distinct(Trace.thread_id)).label("threads"),
                func.count(func.distinct(Trace.user_id)).label("active_users"),
            )
            .where(*trace_scope_filters(project, start=start, end=end, **filters))
            .group_by(label)
            .order_by(label)
        )
    ).all()
    return {
        str(r.bucket): (
            int(r.traces or 0),
            int(r.attributed or 0),
            int(r.threads or 0),
            int(r.active_users or 0),
        )
        for r in rows
    }


async def _window_totals(
    db: AsyncSession,
    project: Project,
    *,
    start: datetime,
    end: datetime,
    filters: dict,
) -> tuple[int, int, int, int]:
    """(traces, traces_attributed, threads, active_users) for a whole window."""
    row = (
        await db.execute(
            select(
                func.count(Trace.id).label("traces"),
                func.sum(case((Trace.user_id.isnot(None), 1), else_=0)).label("attributed"),
                func.count(func.distinct(Trace.thread_id)).label("threads"),
                func.count(func.distinct(Trace.user_id)).label("active_users"),
            ).where(*trace_scope_filters(project, start=start, end=end, **filters))
        )
    ).one()
    return (
        int(row.traces or 0),
        int(row.attributed or 0),
        int(row.threads or 0),
        int(row.active_users or 0),
    )


def _rolling_at(
    activity: dict[str, set[str]], available: bool, at: date
) -> tuple[int | None, int | None, int | None, float | None]:
    if not available:
        return None, None, None, None
    dau = rolling_active(activity, at, DAU_DAYS)
    wau = rolling_active(activity, at, WAU_DAYS)
    mau = rolling_active(activity, at, MAU_DAYS)
    return dau, wau, mau, stickiness(dau, mau)


async def compute_adoption_overview(
    db: AsyncSession,
    project: Project,
    *,
    start: datetime,
    end: datetime,
    bucket: Bucket,
    axis: list[str],
    previous: tuple[datetime, datetime],
    filters: dict,
) -> AdoptionOverview:
    activity, rolling_available = await _activity_matrix(
        db, project, start=start, end=end, filters=filters
    )
    first_seen = await _first_seen(
        db, project, start=start, end=end, bucket=bucket, filters=filters
    )
    baseline = await _baseline_users(db, project, start=start, filters=filters)
    volume = await _volume(db, project, start=start, end=end, bucket=bucket, filters=filters)

    active_by_bucket = bucket_active_users(activity, axis, bucket)
    cumulative = cumulative_unique(first_seen, axis, baseline)
    window_end = ensure_utc(end).date()

    points: list[AdoptionBucketPoint] = []
    for idx, label in enumerate(axis):
        traces, attributed, threads, active_from_sql = volume.get(label, (0, 0, 0, 0))
        active = active_by_bucket.get(label, set())
        # The activity matrix is authoritative when available (it is what new/returning is
        # derived from); fall back to the SQL count when the guard tripped.
        active_count = len(active) if rolling_available else active_from_sql
        new_users, returning_users = split_new_returning(active, first_seen, label)
        # Evaluate the rolling windows at the bucket's end, clamped to the window end so
        # the trailing partial bucket is not measured into the future.
        at = min(bucket_end(label, bucket).date() - timedelta(days=1), window_end)
        dau, wau, mau, stick = _rolling_at(activity, rolling_available, at)
        points.append(
            AdoptionBucketPoint(
                bucket=label,
                active_users=active_count,
                new_users=new_users if rolling_available else 0,
                returning_users=returning_users if rolling_available else 0,
                cumulative_users=cumulative[idx],
                traces=traces,
                traces_attributed=attributed,
                threads=threads,
                avg_traces_per_active_user=safe_rate(attributed, active_count, digits=2),
                dau=dau,
                wau=wau,
                mau=mau,
                stickiness=stick,
            )
        )

    traces, attributed, threads, active_users = await _window_totals(
        db, project, start=start, end=end, filters=filters
    )
    prev_traces, prev_attributed, prev_threads, prev_active = await _window_totals(
        db, project, start=previous[0], end=previous[1], filters=filters
    )

    dau, wau, mau, stick = _rolling_at(activity, rolling_available, window_end)
    new_total = sum(1 for label in first_seen.values() if label in set(axis))
    avg_per_user = safe_rate(attributed, active_users, digits=2)
    prev_avg_per_user = safe_rate(prev_attributed, prev_active, digits=2)

    return AdoptionOverview(
        points=points,
        totals=AdoptionTotals(
            active_users=active_users,
            new_users=new_total,
            returning_users=max(active_users - new_total, 0),
            cumulative_users=cumulative[-1] if cumulative else baseline,
            traces=traces,
            traces_attributed=attributed,
            threads=threads,
            avg_traces_per_active_user=avg_per_user,
            dau=dau,
            wau=wau,
            mau=mau,
            stickiness=stick,
        ),
        growth=AdoptionGrowth(
            traces=Delta(
                current=traces, previous=prev_traces, change_pct=pct_change(traces, prev_traces)
            ),
            threads=Delta(
                current=threads, previous=prev_threads, change_pct=pct_change(threads, prev_threads)
            ),
            active_users=Delta(
                current=active_users,
                previous=prev_active,
                change_pct=pct_change(active_users, prev_active),
            ),
            avg_traces_per_active_user=Delta(
                current=avg_per_user,
                previous=prev_avg_per_user,
                change_pct=pct_change(avg_per_user, prev_avg_per_user),
            ),
        ),
        rolling_available=rolling_available,
    )
