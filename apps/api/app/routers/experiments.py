"""Experiment management endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section
from app.db import get_db
from app.models.models import Experiment
from app.models.project import Project
from app.schemas.experiments import (
    ExperimentCreate,
    ExperimentListResponse,
    ExperimentResponse,
    ExperimentUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/experiments", tags=["experiments"], dependencies=[require_section("evaluate", "datasets")])


@router.get("", response_model=ExperimentListResponse)
async def list_experiments(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List all experiments for the current project."""
    result = await db.execute(
        select(Experiment)
        .where(Experiment.project_id == project.id)
        .order_by(Experiment.name)
    )
    experiments = result.scalars().all()
    return ExperimentListResponse(
        data=[ExperimentResponse.model_validate(e) for e in experiments]
    )


@router.post("", response_model=ExperimentResponse, status_code=201)
async def create_experiment(
    body: ExperimentCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Create a new experiment."""
    # Check for name uniqueness
    existing = await db.execute(
        select(Experiment).where(
            Experiment.project_id == project.id,
            Experiment.name == body.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "DUPLICATE_NAME", "message": f"Experiment '{body.name}' already exists."}},
        )

    experiment = Experiment(
        project_id=project.id,
        name=body.name,
        description=body.description,
        variables=body.variables,
    )
    db.add(experiment)
    await db.commit()
    await db.refresh(experiment)
    return ExperimentResponse.model_validate(experiment)


@router.get("/{experiment_id}", response_model=ExperimentResponse)
async def get_experiment(
    experiment_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get a single experiment by ID."""
    result = await db.execute(
        select(Experiment).where(
            Experiment.id == experiment_id,
            Experiment.project_id == project.id,
        )
    )
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Experiment not found"}},
        )
    return ExperimentResponse.model_validate(experiment)


@router.put("/{experiment_id}", response_model=ExperimentResponse)
async def update_experiment(
    experiment_id: UUID,
    body: ExperimentUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Update an experiment."""
    result = await db.execute(
        select(Experiment).where(
            Experiment.id == experiment_id,
            Experiment.project_id == project.id,
        )
    )
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Experiment not found"}},
        )

    if body.name is not None and body.name != experiment.name:
        # Check uniqueness of new name
        dup = await db.execute(
            select(Experiment).where(
                Experiment.project_id == project.id,
                Experiment.name == body.name,
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail={"error": {"code": "DUPLICATE_NAME", "message": f"Experiment '{body.name}' already exists."}},
            )
        experiment.name = body.name

    if body.description is not None:
        experiment.description = body.description
    if body.variables is not None:
        experiment.variables = body.variables

    experiment.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(experiment)
    return ExperimentResponse.model_validate(experiment)


@router.delete("/{experiment_id}", status_code=204)
async def delete_experiment(
    experiment_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Delete an experiment."""
    result = await db.execute(
        select(Experiment).where(
            Experiment.id == experiment_id,
            Experiment.project_id == project.id,
        )
    )
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Experiment not found"}},
        )

    await db.delete(experiment)
    await db.commit()
