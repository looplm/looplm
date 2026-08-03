"""Shared helper for the include/exclude end-user filter used across Observe endpoints.

Exists mainly to get the exclude side right. A bare ``~Trace.user_id.in_([...])`` silently
drops every trace whose ``user_id`` is NULL, because SQL evaluates ``NULL NOT IN (…)`` to NULL
rather than true. That matters as soon as excluding a group of internal users becomes routine:
hiding staff would also hide all anonymous traffic. ``user_id_filters`` keeps unattributed
traces visible.
"""

from __future__ import annotations

from sqlalchemy import or_

from app.models.models import Trace


def user_id_filters(
    include_user_ids: list[str] | None,
    exclude_user_ids: list[str] | None,
) -> list:
    """Return SQLAlchemy criteria for an include/exclude end-user filter.

    Both lists empty (or None) means no filtering. Include wins nothing special over
    exclude — callers that pass both get the intersection, same as before.
    """
    filters: list = []
    if include_user_ids:
        filters.append(Trace.user_id.in_(include_user_ids))
    if exclude_user_ids:
        filters.append(
            or_(Trace.user_id.is_(None), ~Trace.user_id.in_(exclude_user_ids))
        )
    return filters
