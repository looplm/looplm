"""Evaluator definition endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section, require_write
from app.db import get_db
from app.models.models import Evaluator
from app.models.project import Project
from app.models.user import User
from app.schemas.evaluators import (
    EvaluatorCreate,
    EvaluatorImport,
    EvaluatorImportResponse,
    EvaluatorListResponse,
    EvaluatorResponse,
    EvaluatorUpdate,
    GenerateExpressionRequest,
    GenerateExpressionResponse,
)
from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService
from app.services.llm_usage_tracker import record_llm_usage
from app.services.safe_expression import (
    build_generation_system_prompt,
    strip_expression,
    validate_expression,
)

from .evaluator_helpers import (
    _enrich_with_stats,
    _evaluator_type_value,
    default_evaluator_category,
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
        category=body.category.value if body.category else default_evaluator_category(body.name, body.config),
    )
    db.add(ev)
    await db.flush()
    await db.refresh(ev)

    enriched = await _enrich_with_stats([ev], project.id, db)
    return enriched[0]


@router.post(
    "/generate-expression",
    response_model=GenerateExpressionResponse,
    dependencies=[require_write("evaluate", "evaluators")],
)
async def generate_expression(
    body: GenerateExpressionRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Turn a plain-language check into a Code-evaluator DSL expression via the LLM.

    Returns the generated boolean expression plus whether it parses and uses only allowed
    constructs/variables (validated against the safe evaluator). The caller can edit it before
    saving; invalid output is still returned so the reviewer sees what the model proposed.
    """
    description = (body.description or "").strip()
    if not description:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "EMPTY", "message": "Describe the check to generate."}},
        )
    try:
        llm = AnalysisLlmService(user_settings=user.settings, project_settings=project.settings)
    except AnalysisLlmConfigError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "LLM_NOT_CONFIGURED", "message": str(exc)}},
        ) from exc

    messages = [
        {"role": "system", "content": build_generation_system_prompt()},
        {"role": "user", "content": description},
    ]
    try:
        content, usage = await llm.tracked_chat_completion(messages=messages, temperature=0.0)
    except AnalysisLlmConfigError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "LLM_NOT_CONFIGURED", "message": str(exc)}},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Expression generation failed")
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "GENERATION_FAILED", "message": f"LLM call failed: {exc}"}},
        ) from exc

    await record_llm_usage(
        db,
        project_id=project.id,
        service_name="evaluators",
        function_name="generate_expression",
        provider=llm.provider,
        model=llm.model,
        usage=usage,
        request_metadata={"description": description[:200]},
    )

    expression = strip_expression(content or "")
    error = validate_expression(expression)
    return GenerateExpressionResponse(expression=expression, valid=error is None, error=error)


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
            category=item.category.value if item.category else default_evaluator_category(item.name, item.config),
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
