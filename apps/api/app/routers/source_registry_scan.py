"""Bulk source-completeness scan endpoints (Data Sources 'Source review' tab).

Runs the per-source resolve+chunk analysis across every source as a background
job, resilient to the index's rate-limiting, and persists a verdict per source.
Sources that error after retries form a dead-letter set that ``scope='dlq'``
re-scans — mirroring the evaluations rerun. Shares the ``/api/source-registry``
prefix with :mod:`app.routers.source_registry` (registered as a second router).
"""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section, require_write
from app.db import async_session, get_db
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.models.source_registry import SourceScanResult, SourceScanRun
from app.routers.source_registry_scan_worker import run_source_scan
from app.schemas.source_registry import (
    SourceScanCreateResponse,
    SourceScanRequest,
    SourceScanResultItem,
    SourceScanResultsResponse,
    SourceScanRunResponse,
)

router = APIRouter(
    prefix="/api/source-registry",
    tags=["source-registry"],
    dependencies=[require_section("observe", "data-sources")],
)

# Keep background scan tasks referenced so they aren't garbage-collected mid-run.
_scan_tasks: dict[UUID, asyncio.Task] = {}


def _not_found(what: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail={"error": {"code": "NOT_FOUND", "message": f"{what} not found"}}
    )


async def _provider_or_404(db: AsyncSession, provider_id: UUID, project: Project) -> IndexProvider:
    provider = (
        await db.execute(
            select(IndexProvider).where(
                IndexProvider.id == provider_id, IndexProvider.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if provider is None:
        raise _not_found("Index provider")
    return provider


@router.post(
    "/scans",
    response_model=SourceScanCreateResponse,
    status_code=202,
    dependencies=[require_write("observe", "data-sources")],
)
async def create_scan(
    body: SourceScanRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Start a background completeness scan over the provider's sources."""
    await _provider_or_404(db, body.provider_id, project)
    run = SourceScanRun(
        project_id=project.id,
        provider_id=body.provider_id,
        scope=body.scope,
        status="pending",
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    scan_id = run.id
    # Commit before spawning: the worker opens its own session and must see the row.
    await db.commit()

    task = asyncio.create_task(
        run_source_scan(
            scan_id=scan_id,
            project_id=project.id,
            provider_id=body.provider_id,
            scope=body.scope,
            db_factory=async_session,
        )
    )
    _scan_tasks[scan_id] = task
    task.add_done_callback(lambda _t, sid=scan_id: _scan_tasks.pop(sid, None))
    return SourceScanCreateResponse(scan_id=scan_id, status="pending")


async def _scan_or_404(db: AsyncSession, scan_id: UUID, project: Project) -> SourceScanRun:
    run = (
        await db.execute(
            select(SourceScanRun).where(
                SourceScanRun.id == scan_id, SourceScanRun.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise _not_found("Source scan")
    return run


@router.get("/scans/{scan_id}", response_model=SourceScanRunResponse)
async def get_scan(
    scan_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    return await _scan_or_404(db, scan_id, project)


@router.post(
    "/scans/{scan_id}/cancel",
    response_model=SourceScanRunResponse,
    dependencies=[require_write("observe", "data-sources")],
)
async def cancel_scan(
    scan_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Stop a pending/running scan. No-op if it already finished."""
    run = await _scan_or_404(db, scan_id, project)
    if run.status not in ("pending", "running"):
        return run
    task = _scan_tasks.get(scan_id)
    if task is not None and not task.done():
        task.cancel()
    run.status = "cancelled"
    run.error = "Cancelled by user"
    run.completed_at = datetime.now(timezone.utc)
    return run


@router.get("/scans", response_model=SourceScanRunResponse)
async def latest_scan(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """The most recent scan run for a provider (404 if none yet)."""
    run = (
        await db.execute(
            select(SourceScanRun)
            .where(
                SourceScanRun.project_id == project.id,
                SourceScanRun.provider_id == provider_id,
            )
            .order_by(SourceScanRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        raise _not_found("Source scan")
    return run


@router.get("/scan-results", response_model=SourceScanResultsResponse)
async def scan_results(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Current per-source scan verdicts + rollup counts + the latest run."""
    rows = list(
        (
            await db.execute(
                select(SourceScanResult).where(
                    SourceScanResult.project_id == project.id,
                    SourceScanResult.provider_id == provider_id,
                )
            )
        )
        .scalars()
        .all()
    )
    summary = {
        "total": len(rows),
        "not_indexed": sum(1 for r in rows if r.execution_status == "ok" and not r.resolved),
        "incomplete": sum(
            1 for r in rows if r.execution_status == "ok" and r.missing_chunk_count > 0
        ),
        "errored": sum(1 for r in rows if r.execution_status == "error"),
        "ok": sum(
            1
            for r in rows
            if r.execution_status == "ok" and r.resolved and r.missing_chunk_count == 0
        ),
    }
    latest = (
        await db.execute(
            select(SourceScanRun)
            .where(
                SourceScanRun.project_id == project.id,
                SourceScanRun.provider_id == provider_id,
            )
            .order_by(SourceScanRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return SourceScanResultsResponse(
        data=[SourceScanResultItem.model_validate(r) for r in rows],
        summary=summary,
        latest_run=SourceScanRunResponse.model_validate(latest) if latest else None,
    )
