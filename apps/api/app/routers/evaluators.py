"""Evaluator definition endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section, require_write
from app.db import get_db
from app.models.models import Evaluator
from app.models.project import Project
from app.schemas.evaluators import (
    EvaluatorCreate,
    EvaluatorImport,
    EvaluatorImportResponse,
    EvaluatorListResponse,
    EvaluatorResponse,
    EvaluatorUpdate,
)

from .evaluator_helpers import (
    _enrich_with_stats,
    _evaluator_type_value,
    discover_and_sync_evaluators,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evaluators", tags=["evaluators"], dependencies=[require_section("evaluate", "evaluators")])


@router.get("", response_model=EvaluatorListResponse)
async def list_evaluators(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List all evaluators for the project, enriched with stats."""
    result = await db.execute(
        select(Evaluator)
        .where(Evaluator.project_id == project.id)
        .order_by(Evaluator.name)
    )
    evaluators = list(result.scalars().all())

    data = await _enrich_with_stats(evaluators, project.id, db)
    return EvaluatorListResponse(data=data, total=len(data))


@router.get("/{evaluator_id}", response_model=EvaluatorResponse)
async def get_evaluator(
    evaluator_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get a single evaluator with stats."""
    result = await db.execute(
        select(Evaluator).where(Evaluator.id == evaluator_id, Evaluator.project_id == project.id)
    )
    ev = result.scalar_one_or_none()
    if not ev:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Evaluator not found"}},
        )

    enriched = await _enrich_with_stats([ev], project.id, db)
    return enriched[0]


@router.post(
    "",
    response_model=EvaluatorResponse,
    status_code=201,
    dependencies=[require_write("evaluate", "evaluators")],
)
async def create_evaluator(
    body: EvaluatorCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Create a new evaluator."""
    ev_type = _evaluator_type_value(body.type)

    # Check for duplicate name
    existing = await db.execute(
        select(Evaluator).where(Evaluator.project_id == project.id, Evaluator.name == body.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "DUPLICATE", "message": f"Evaluator '{body.name}' already exists"}},
        )

    ev = Evaluator(
        project_id=project.id,
        name=body.name,
        display_name=body.display_name,
        type=ev_type,
        description=body.description,
        relevance=body.relevance,
        affects_pass=body.affects_pass,
        config=body.config,
        source=body.source,
    )
    db.add(ev)
    await db.flush()
    await db.refresh(ev)

    enriched = await _enrich_with_stats([ev], project.id, db)
    return enriched[0]


@router.patch(
    "/{evaluator_id}",
    response_model=EvaluatorResponse,
    dependencies=[require_write("evaluate", "evaluators")],
)
async def update_evaluator(
    evaluator_id: UUID,
    body: EvaluatorUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Update an evaluator."""
    result = await db.execute(
        select(Evaluator).where(Evaluator.id == evaluator_id, Evaluator.project_id == project.id)
    )
    ev = result.scalar_one_or_none()
    if not ev:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Evaluator not found"}},
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(ev, field, value)
    ev.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(ev)

    enriched = await _enrich_with_stats([ev], project.id, db)
    return enriched[0]


@router.delete(
    "/{evaluator_id}",
    status_code=204,
    dependencies=[require_write("evaluate", "evaluators")],
)
async def delete_evaluator(
    evaluator_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Delete an evaluator."""
    result = await db.execute(
        select(Evaluator).where(Evaluator.id == evaluator_id, Evaluator.project_id == project.id)
    )
    ev = result.scalar_one_or_none()
    if not ev:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Evaluator not found"}},
        )
    await db.delete(ev)


@router.post(
    "/import",
    response_model=EvaluatorImportResponse,
    status_code=201,
    dependencies=[require_write("evaluate", "evaluators")],
)
async def import_evaluators(
    body: EvaluatorImport,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Bulk-import evaluators from JSON. Skips duplicates by name."""
    created = 0
    skipped = 0
    created_evaluators: list[Evaluator] = []

    for item in body.evaluators:
        ev_type = _evaluator_type_value(item.type)

        existing = await db.execute(
            select(Evaluator).where(Evaluator.project_id == project.id, Evaluator.name == item.name)
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        ev = Evaluator(
            project_id=project.id,
            name=item.name,
            display_name=item.display_name,
            type=ev_type,
            description=item.description,
            relevance=item.relevance,
            affects_pass=item.affects_pass,
            config=item.config,
            source=item.source,
        )
        db.add(ev)
        created_evaluators.append(ev)
        created += 1

    if created > 0:
        await db.flush()
        for ev in created_evaluators:
            await db.refresh(ev)

    logger.info("Imported evaluators for project %s: %d created, %d skipped", project.id, created, skipped)

    data = await _enrich_with_stats(created_evaluators, project.id, db)
    return EvaluatorImportResponse(created=created, skipped=skipped, total=len(body.evaluators), data=data)


@router.post(
    "/sync",
    response_model=EvaluatorListResponse,
    dependencies=[require_write("evaluate", "evaluators")],
)
async def sync_evaluators(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Discover evaluators from existing eval results and auto-create entries."""
    created, updated = await discover_and_sync_evaluators(project.id, db)

    logger.info("Synced evaluators for project %s: %d new, %d backfilled", project.id, created, updated)

    # Return full list
    result = await db.execute(
        select(Evaluator)
        .where(Evaluator.project_id == project.id)
        .order_by(Evaluator.name)
    )
    evaluators = list(result.scalars().all())
    data = await _enrich_with_stats(evaluators, project.id, db)
    return EvaluatorListResponse(data=data, total=len(data))
