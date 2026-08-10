"""The standard Observe trace filter, in one place.

This block (project integrations + time window + environment + include/exclude users +
the per-project trace-name allowlist) is duplicated in ``routers/dashboard.py``,
``routers/analytics.py``, ``routers/trace_threads.py``, ``routers/costs_overview.py``
and ``services/feedback_stats_service.py``. Every copy has to get the NULL-safe user
exclusion right, so it is worth having one.

Ordering contract: **the time bounds always come first** in the returned list, and in
``(start, end)`` order. ``routers/dashboard.py`` builds its previous-window query as
``[prev_start_bound, prev_end_bound, *base_filter[2:]]``, i.e. it slices the time bounds
off positionally. Any change to the order below has to account for that.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from app.models.models import Integration, Trace
from app.models.project import Project
from app.services.observe_filter import get_observe_trace_names
from app.services.user_filter import user_id_filters


def trace_scope_filters(
    project: Project,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    environment: str | None = None,
    include_user_ids: list[str] | None = None,
    exclude_user_ids: list[str] | None = None,
    integration_id: UUID | None = None,
) -> list:
    """Build the shared Observe trace filter criteria.

    Passing neither ``start`` nor ``end`` gives an all-history scope, which is what the
    adoption first-seen lookup needs: "when did this user first appear" is not a
    question about the selected window.
    """
    filters: list = []
    # Time bounds first — see the ordering contract in the module docstring.
    if start is not None:
        filters.append(Trace.start_time >= start)
    if end is not None:
        filters.append(Trace.start_time <= end)

    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    filters.append(Trace.integration_id.in_(project_integration_ids))
    if integration_id:
        filters.append(Trace.integration_id == integration_id)
    if environment:
        filters.append(Trace.trace_metadata["environment"].astext == environment)
    filters.extend(user_id_filters(include_user_ids, exclude_user_ids))

    trace_names = get_observe_trace_names(project)
    if trace_names:
        filters.append(Trace.name.in_(trace_names))
    return filters
