"""Thread-grouped trace listing endpoint."""

import logging
from datetime import datetime
from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, literal, select, Text, cast, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Integration, Trace
from app.models.project import Project
from app.services.observe_filter import get_observe_trace_names
from app.auth import get_current_project
from app.db import get_db
from app.schemas.traces import (
    PaginationInfo,
    ThreadListResponse,
    ThreadOrderItem,
    ThreadSummary,
    TraceListItem,
)

from .trace_helpers import _multi_filter, _parse_multi

logger = logging.getLogger(__name__)

router = APIRouter(tags=["traces"])


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads(
    integration_id: UUID | None = None,
    status: str | None = None,
    status_mode: str = "include",
    name: str | None = None,
    name_mode: str = "include",
    thread_id: str | None = None,
    thread_id_mode: str = "include",
    search: str | None = None,
    search_mode: str = "include",
    environment: str | None = None,
    environment_mode: str = "include",
    include_user_ids: str | None = None,
    exclude_user_ids: str | None = None,
    start_after: datetime | None = None,
    start_before: datetime | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List traces grouped by thread_id. Threads and standalone traces are paginated together."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    # Build base filter conditions
    conditions = [Trace.integration_id.in_(project_integration_ids)]
    if integration_id:
        conditions.append(Trace.integration_id == integration_id)

    # Project-level Observe trace-name scope
    observe_names = get_observe_trace_names(project)
    if observe_names:
        conditions.append(Trace.name.in_(observe_names))

    status_vals = _parse_multi(status)
    if status_vals:
        conditions.append(_multi_filter(cast(Trace.status, Text), status_vals, status_mode))
    name_vals = _parse_multi(name)
    if name_vals:
        conditions.append(_multi_filter(Trace.name, name_vals, name_mode, ilike=True))
    thread_vals = _parse_multi(thread_id)
    if thread_vals:
        conditions.append(_multi_filter(Trace.thread_id, thread_vals, thread_id_mode))
    search_vals = _parse_multi(search)
    if search_vals:
        conditions.append(_multi_filter(cast(Trace.input, Text), search_vals, search_mode, ilike=True))
    env_vals = _parse_multi(environment)
    if env_vals:
        conditions.append(_multi_filter(Trace.trace_metadata["environment"].astext, env_vals, environment_mode))
    inc_uids = _parse_multi(include_user_ids)
    if inc_uids:
        conditions.append(Trace.user_id.in_(inc_uids))
    exc_uids = _parse_multi(exclude_user_ids)
    if exc_uids:
        conditions.append(~Trace.user_id.in_(exc_uids))
    if start_after:
        conditions.append(Trace.start_time > start_after)
    if start_before:
        conditions.append(Trace.start_time < start_before)

    # Build a unified list of thread groups and standalone traces sorted by time desc.
    # Each "item" is either a thread_id (grouped) or a standalone trace_id.
    thread_items_q = (
        select(
            Trace.thread_id.label("item_id"),
            literal("thread").label("item_type"),
            func.max(Trace.start_time).label("sort_time"),
        )
        .where(*conditions, Trace.thread_id.isnot(None))
        .group_by(Trace.thread_id)
    )
    standalone_items_q = (
        select(
            cast(Trace.id, Text).label("item_id"),
            literal("trace").label("item_type"),
            Trace.start_time.label("sort_time"),
        )
        .where(*conditions, Trace.thread_id.is_(None))
    )

    combined = union_all(thread_items_q, standalone_items_q).subquery()
    count_q = select(func.count()).select_from(combined)
    total = (await db.execute(count_q)).scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0
    offset = (page - 1) * per_page

    page_q = (
        select(combined.c.item_id, combined.c.item_type)
        # item_id breaks ties between same-sort_time rows for stable paging.
        .order_by(combined.c.sort_time.desc(), combined.c.item_id.desc())
        .offset(offset)
        .limit(per_page)
    )
    page_result = await db.execute(page_q)
    page_items = page_result.all()

    # Separate thread_ids and standalone trace_ids, preserving order
    ordered_keys: list[tuple[str, str]] = [(row.item_id, row.item_type) for row in page_items]
    tid_list = [item_id for item_id, item_type in ordered_keys if item_type == "thread"]
    standalone_ids = [item_id for item_id, item_type in ordered_keys if item_type == "trace"]

    # Fetch thread traces
    thread_map: dict[str, ThreadSummary] = {}
    if tid_list:
        traces_q = (
            select(Trace)
            .where(*conditions, Trace.thread_id.in_(tid_list))
            .order_by(Trace.start_time.asc())
        )
        traces_result = await db.execute(traces_q)
        all_traces = traces_result.scalars().all()

        grouped: dict[str, list] = {tid: [] for tid in tid_list}
        for t in all_traces:
            grouped[t.thread_id].append(t)

        for tid in tid_list:
            group = grouped[tid]
            if not group:
                continue
            first = group[0]
            last = group[-1]
            total_dur = sum(t.duration_ms for t in group if t.duration_ms) or None
            has_fail = any(t.status and t.status.value == "failure" for t in group)
            thread_map[tid] = ThreadSummary(
                thread_id=tid,
                trace_count=len(group),
                first_time=first.start_time,
                last_time=last.start_time,
                total_duration_ms=total_dur,
                has_failures=has_fail,
                traces=group,
            )

    # Fetch standalone traces
    standalone_map: dict[str, Trace] = {}
    if standalone_ids:
        standalone_q = select(Trace).where(cast(Trace.id, Text).in_(standalone_ids))
        standalone_result = await db.execute(standalone_q)
        for t in standalone_result.scalars().all():
            standalone_map[str(t.id)] = t

    # Assemble in the correct interleaved order
    threads_data: list[ThreadSummary] = []
    standalone_data: list[TraceListItem] = []
    order: list[ThreadOrderItem] = []
    for item_id, item_type in ordered_keys:
        if item_type == "thread" and item_id in thread_map:
            threads_data.append(thread_map[item_id])
            order.append(ThreadOrderItem(type="thread", id=item_id))
        elif item_type == "trace" and item_id in standalone_map:
            standalone_data.append(standalone_map[item_id])
            order.append(ThreadOrderItem(type="trace", id=item_id))

    return ThreadListResponse(
        data=threads_data,
        standalone_traces=standalone_data,
        order=order,
        pagination=PaginationInfo(page=page, per_page=per_page, total=total, total_pages=total_pages),
    )
