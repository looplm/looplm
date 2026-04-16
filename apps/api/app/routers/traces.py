"""Trace list/filter endpoints."""

import logging
from datetime import datetime
from math import ceil
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, Text, cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth import get_current_project, require_section
from app.db import get_db
from app.models.models import Integration, IntegrationType, JsonImport, SyncStatus, Trace, TraceStatus
from app.models.project import Project
from app.schemas.traces import (
    PaginationInfo,
    TraceImportRequest,
    TraceListItem,
    TraceListResponse,
)

from .trace_helpers import _multi_filter, _parse_multi

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/traces", tags=["traces"], dependencies=[require_section("observe", "traces")])

from .trace_threads import router as trace_threads_router
router.include_router(trace_threads_router)


@router.post("/import", status_code=201)
async def import_traces(
    body: TraceImportRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Import traces from a JSON file upload."""
    from app.encryption import encrypt_api_key

    if not body.traces:
        raise HTTPException(status_code=400, detail="No traces provided")

    # Find or create json_file integration
    result = await db.execute(
        select(Integration).where(
            Integration.project_id == project.id,
            Integration.type == IntegrationType.json_file,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        integration = Integration(
            project_id=project.id,
            type=IntegrationType.json_file,
            name="JSON Import",
            api_key=encrypt_api_key("json_file_placeholder"),
            sync_status=SyncStatus.idle,
        )
        db.add(integration)
        await db.flush()

    count = 0
    for item in body.traces:
        start = datetime.fromisoformat(item.start_time) if item.start_time else datetime.utcnow()
        end = datetime.fromisoformat(item.end_time) if item.end_time else None
        status = None
        if item.status:
            try:
                status = TraceStatus(item.status)
            except ValueError:
                pass

        trace = Trace(
            integration_id=integration.id,
            external_id=str(uuid4()),
            name=item.name,
            input=item.input,
            output=item.output,
            status=status,
            start_time=start,
            end_time=end,
            duration_ms=item.duration_ms,
            error_message=item.error_message,
            trace_metadata=item.metadata or {},
            thread_id=item.thread_id,
        )
        db.add(trace)
        count += 1

    # Record import history
    db.add(JsonImport(
        project_id=project.id,
        entity_type="traces",
        filename=body.filename,
        record_count=count,
    ))

    await db.flush()
    return {"imported": count, "message": f"Imported {count} traces"}


@router.get("/environments")
async def list_environments(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Return distinct environment values from trace metadata."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    env_col = Trace.trace_metadata["environment"].astext
    result = await db.execute(
        select(env_col)
        .where(
            Trace.integration_id.in_(project_integration_ids),
            env_col.isnot(None),
            env_col != "",
        )
        .distinct()
        .order_by(env_col)
    )
    return [row[0] for row in result.all()]


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Return distinct user_id values with optional username from metadata."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    username_col = Trace.trace_metadata["username"].astext
    result = await db.execute(
        select(
            Trace.user_id,
            func.max(username_col).label("username"),
        )
        .where(
            Trace.integration_id.in_(project_integration_ids),
            Trace.user_id.isnot(None),
            Trace.user_id != "",
        )
        .group_by(Trace.user_id)
        .order_by(Trace.user_id)
    )
    return [
        {"user_id": row.user_id, "username": row.username}
        for row in result.all()
    ]


@router.get("/names")
async def list_names(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Return distinct trace names."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    result = await db.execute(
        select(func.distinct(Trace.name))
        .where(
            Trace.integration_id.in_(project_integration_ids),
            Trace.name.isnot(None),
            Trace.name != "",
        )
        .order_by(Trace.name)
    )
    return [row[0] for row in result.all()]


@router.get("/thread-ids")
async def list_thread_ids(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Return distinct thread IDs."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    result = await db.execute(
        select(func.distinct(Trace.thread_id))
        .where(
            Trace.integration_id.in_(project_integration_ids),
            Trace.thread_id.isnot(None),
            Trace.thread_id != "",
        )
        .order_by(Trace.thread_id)
    )
    return [row[0] for row in result.all()]


@router.get("/statuses")
async def list_statuses(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Return distinct status values."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    result = await db.execute(
        select(func.distinct(cast(Trace.status, Text)))
        .where(
            Trace.integration_id.in_(project_integration_ids),
            Trace.status.isnot(None),
        )
        .order_by(cast(Trace.status, Text))
    )
    return [row[0] for row in result.all()]


@router.get("", response_model=TraceListResponse)
async def list_traces(
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
    root_only: bool = False,
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    # Support limit/offset as aliases for per_page/page
    if limit is not None:
        per_page = limit
    if offset is not None:
        page = (offset // per_page) + 1

    # Scope to project's integrations
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    query = select(Trace).where(Trace.integration_id.in_(project_integration_ids))
    count_query = select(func.count(Trace.id)).where(Trace.integration_id.in_(project_integration_ids))

    if root_only:
        query = query.where(Trace.parent_trace_id.is_(None))
        count_query = count_query.where(Trace.parent_trace_id.is_(None))
    if integration_id:
        query = query.where(Trace.integration_id == integration_id)
        count_query = count_query.where(Trace.integration_id == integration_id)

    # Multi-value filters with include/exclude
    status_vals = _parse_multi(status)
    if status_vals:
        f = _multi_filter(cast(Trace.status, Text), status_vals, status_mode)
        query = query.where(f)
        count_query = count_query.where(f)

    name_vals = _parse_multi(name)
    if name_vals:
        f = _multi_filter(Trace.name, name_vals, name_mode, ilike=True)
        query = query.where(f)
        count_query = count_query.where(f)

    thread_vals = _parse_multi(thread_id)
    if thread_vals:
        f = _multi_filter(Trace.thread_id, thread_vals, thread_id_mode)
        query = query.where(f)
        count_query = count_query.where(f)

    search_vals = _parse_multi(search)
    if search_vals:
        f = _multi_filter(cast(Trace.input, Text), search_vals, search_mode, ilike=True)
        query = query.where(f)
        count_query = count_query.where(f)

    env_vals = _parse_multi(environment)
    if env_vals:
        env_col = Trace.trace_metadata["environment"].astext
        f = _multi_filter(env_col, env_vals, environment_mode)
        query = query.where(f)
        count_query = count_query.where(f)

    inc_uids = _parse_multi(include_user_ids)
    if inc_uids:
        query = query.where(Trace.user_id.in_(inc_uids))
        count_query = count_query.where(Trace.user_id.in_(inc_uids))
    exc_uids = _parse_multi(exclude_user_ids)
    if exc_uids:
        query = query.where(~Trace.user_id.in_(exc_uids))
        count_query = count_query.where(~Trace.user_id.in_(exc_uids))

    if start_after:
        query = query.where(Trace.start_time > start_after)
        count_query = count_query.where(Trace.start_time > start_after)
    if start_before:
        query = query.where(Trace.start_time < start_before)
        count_query = count_query.where(Trace.start_time < start_before)

    total = (await db.execute(count_query)).scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = query.order_by(Trace.start_time.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    traces = list(result.scalars().all())

    # Batch-fetch child run counts for root traces
    if root_only and traces:
        trace_ids = [t.id for t in traces]
        ChildTrace = aliased(Trace)
        counts_result = await db.execute(
            select(ChildTrace.root_trace_id, func.count(ChildTrace.id))
            .where(ChildTrace.root_trace_id.in_(trace_ids))
            .group_by(ChildTrace.root_trace_id)
        )
        count_map = dict(counts_result.all())

        data = []
        for t in traces:
            item = TraceListItem.model_validate(t)
            item.child_run_count = count_map.get(t.id, 0)
            data.append(item)
    else:
        data = traces

    return TraceListResponse(
        data=data,
        pagination=PaginationInfo(page=page, per_page=per_page, total=total, total_pages=total_pages),
    )
