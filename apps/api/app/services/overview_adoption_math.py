"""Pure adoption math, kept out of the query layer so it can be tested directly.

Everything here operates on an "activity matrix": ``{day_label: {user_id, ...}}``. That
shape comes from one grouped query (see ``overview_adoption.py``) and is the single input
for active users per bucket, new vs returning, cumulative unique users and DAU/WAU/MAU.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services.time_buckets import Bucket, bucket_start


def bucket_active_users(
    activity: dict[str, set[str]], axis: list[str], bucket: Bucket
) -> dict[str, set[str]]:
    """Roll a per-day activity matrix up to the requested bucket."""
    axis_set = set(axis)
    out: dict[str, set[str]] = {label: set() for label in axis}
    for day_label, users in activity.items():
        label = bucket_start(date.fromisoformat(day_label), bucket).isoformat()
        if label in axis_set:
            out[label].update(users)
    return out


def split_new_returning(
    active_users: set[str], first_seen_bucket: dict[str, str], label: str
) -> tuple[int, int]:
    """(new, returning) among ``active_users`` for the bucket ``label``.

    A user is new in the bucket their first-ever activity falls into. Because the
    first-seen lookup is unbounded in time, a user who was active before the window
    correctly counts as returning in their first in-window bucket rather than as new.
    """
    new = sum(1 for u in active_users if first_seen_bucket.get(u) == label)
    return new, len(active_users) - new


def cumulative_unique(
    first_seen_bucket: dict[str, str], axis: list[str], baseline: int
) -> list[int]:
    """Running total of distinct users ever seen, one entry per bucket.

    ``baseline`` is the number of distinct users who appeared strictly before the window,
    so the curve continues the real history instead of restarting at zero. Only users
    whose first appearance lands inside the window can add to it.
    """
    per_bucket: dict[str, int] = {label: 0 for label in axis}
    for label in first_seen_bucket.values():
        if label in per_bucket:
            per_bucket[label] += 1
    out: list[int] = []
    running = baseline
    for label in axis:
        running += per_bucket[label]
        out.append(running)
    return out


def rolling_active(activity: dict[str, set[str]], at: date, window_days: int) -> int:
    """Distinct users active in the ``window_days`` ending on ``at`` inclusive."""
    users: set[str] = set()
    for offset in range(window_days):
        day = (at - timedelta(days=offset)).isoformat()
        found = activity.get(day)
        if found:
            users.update(found)
    return len(users)


def stickiness(dau: int | None, mau: int | None) -> float | None:
    """DAU/MAU. None on a zero or missing MAU.

    Not 0.0: a project with no monthly activity is undefined, not 0% sticky, and a
    fabricated zero reads as a regression on the chart.
    """
    if not dau and not mau:
        return None
    if not mau:
        return None
    return round((dau or 0) / mau, 4)
