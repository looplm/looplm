"""Integration endpoints."""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project
from app.config import settings
from app.db import async_session, get_db
from app.encryption import encrypt_api_key
from app.models.models import Integration, SyncStatus
from app.models.project import Project
from app.schemas.integrations import (
    IntegrationCreate,
    IntegrationListResponse,
    IntegrationResponse,
    IntegrationUpdate,
    SyncRequest,
    SyncResponse,
)
from app.services.sync_service import run_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.post("", response_model=IntegrationResponse, status_code=201)
async def create_integration(
    body: IntegrationCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    # Check duplicate name for this project
    existing = await db.execute(
        select(Integration).where(Integration.project_id == project.id, Integration.name == body.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail={"error": {"code": "CONFLICT", "message": "Integration name already exists"}})

    integration = Integration(
        project_id=project.id,
        type=body.type,
        name=body.name,
        api_key=encrypt_api_key(body.api_key or "json_file_placeholder"),
        base_url=body.base_url,
        config=body.config,
        sync_status=SyncStatus.never,
    )
    db.add(integration)
    await db.flush()
    await db.refresh(integration)
    return integration


@router.get("", response_model=IntegrationListResponse)
async def list_integrations(
    type: str | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    query = select(Integration).where(Integration.project_id == project.id)
    if type:
        query = query.where(Integration.type == type)
    result = await db.execute(query.order_by(Integration.created_at.desc()))
    return IntegrationListResponse(data=result.scalars().all())


@router.get("/{integration_id}", response_model=IntegrationResponse)
async def get_integration(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(Integration).where(Integration.id == integration_id, Integration.project_id == project.id)
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Integration not found"}})
    return integration


@router.patch("/{integration_id}", response_model=IntegrationResponse)
async def update_integration(
    integration_id: UUID,
    body: IntegrationUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(Integration).where(Integration.id == integration_id, Integration.project_id == project.id)
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Integration not found"}})

    if body.name is not None:
        # Check duplicate name (excluding current integration)
        existing = await db.execute(
            select(Integration).where(
                Integration.project_id == project.id,
                Integration.name == body.name,
                Integration.id != integration_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail={"error": {"code": "CONFLICT", "message": "Integration name already exists"}})
        integration.name = body.name

    if body.api_key is not None:
        integration.api_key = encrypt_api_key(body.api_key)
    if body.base_url is not None:
        integration.base_url = body.base_url
    if body.config is not None:
        integration.config = body.config

    await db.flush()
    await db.refresh(integration)
    return integration


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(Integration).where(Integration.id == integration_id, Integration.project_id == project.id)
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Integration not found"}})
    if integration.sync_status == SyncStatus.syncing:
        raise HTTPException(status_code=409, detail={"error": {"code": "CONFLICT", "message": "Cannot delete while sync is in progress"}})

    await db.delete(integration)
    return None


@router.post("/{integration_id}/sync", response_model=SyncResponse, status_code=202)
async def trigger_sync(
    integration_id: UUID,
    body: SyncRequest | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(Integration).where(Integration.id == integration_id, Integration.project_id == project.id)
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Integration not found"}})
    if integration.sync_status == SyncStatus.syncing:
        raise HTTPException(status_code=409, detail={"error": {"code": "CONFLICT", "message": "Sync already in progress"}})

    integration.sync_status = SyncStatus.syncing
    integration.last_sync_error = None
    integration.sync_progress_current = None
    integration.sync_progress_total = None
    integration.sync_started_at = datetime.now(timezone.utc)
    integration.sync_phase = None
    integration.sync_message = None
    integration.sync_since = None
    await db.flush()

    since_override = body.since if body else None
    update_existing = body.update_existing if body else False
    task = asyncio.create_task(_run_sync_background(integration.id, since_override, update_existing))
    _sync_tasks[integration.id] = task

    return SyncResponse(integration_id=integration.id, sync_status="syncing")


@router.post("/{integration_id}/sync/stop", status_code=200)
async def stop_sync(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(Integration).where(Integration.id == integration_id, Integration.project_id == project.id)
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Integration not found"}})
    if integration.sync_status != SyncStatus.syncing:
        raise HTTPException(status_code=409, detail={"error": {"code": "CONFLICT", "message": "No sync in progress"}})

    # Cancel the background task if it's still running
    task = _sync_tasks.pop(integration.id, None)
    if task and not task.done():
        task.cancel()

    integration.sync_status = SyncStatus.idle
    integration.last_sync_error = "Sync cancelled by user"
    integration.sync_progress_current = None
    integration.sync_progress_total = None
    integration.sync_started_at = None
    integration.sync_phase = None
    integration.sync_message = None
    integration.sync_since = None
    await db.flush()

    return {"message": "Sync stopped"}


# Track background sync tasks so they can be cancelled
_sync_tasks: dict[UUID, asyncio.Task] = {}


async def _mark_sync_error(integration_id: UUID, message: str, *, only_if_syncing: bool = False) -> None:
    """Record a sync error on a FRESH session.

    Critical: when a sync is cancelled mid-flush (e.g. the timeout below), the
    session run_sync was using is left in an aborted state. Reusing it to record
    the error raises PendingRollbackError, which masks the real cause. Always use
    a clean session here.
    """
    try:
        async with async_session() as db:
            result = await db.execute(select(Integration).where(Integration.id == integration_id))
            integration = result.scalar_one_or_none()
            if integration and (not only_if_syncing or integration.sync_status == SyncStatus.syncing):
                integration.sync_status = SyncStatus.error
                integration.last_sync_error = message
                integration.sync_progress_current = None
                integration.sync_progress_total = None
                integration.sync_started_at = None
                integration.sync_phase = None
                integration.sync_message = None
                integration.sync_since = None
                await db.commit()
    except Exception:
        logger.exception("Failed to record sync error for %s", integration_id)


async def _run_sync_background(integration_id: UUID, since_override: datetime | None = None, update_existing: bool = False) -> None:
    """Run sync in a background task with its own DB session."""
    try:
        async with async_session() as db:
            await asyncio.wait_for(
                run_sync(integration_id, db, since_override=since_override, update_existing=update_existing),
                timeout=settings.sync_timeout_seconds,
            )
    except asyncio.TimeoutError:
        minutes = max(1, settings.sync_timeout_seconds // 60)
        logger.error("Sync timed out for %s after %ss", integration_id, settings.sync_timeout_seconds)
        await _mark_sync_error(integration_id, f"Sync timed out after {minutes} minutes")
    except Exception as e:
        # run_sync records its own errors; this is a backstop for anything that escaped.
        from app.services.sync_service import _format_sync_error
        error_msg = _format_sync_error(e)
        logger.error("Background sync failed for %s: %s", integration_id, error_msg)
        await _mark_sync_error(integration_id, f"Background task failed: {error_msg}", only_if_syncing=True)
