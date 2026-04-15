"""Prompt import & analysis endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section
from app.db import get_db
from app.models.models import JsonImport
from app.models.project import Project
from app.models.user import User
from app.schemas.prompts import (
    PromptImportRequest,
    PromptListResponse,
    PromptOut,
    PromptReviewListResponse,
    PromptReviewResult,
    PromptSyncResponse,
)
from app.services.prompt_analysis import (
    get_prompt,
    import_prompts_from_json,
    list_prompts,
    list_reviews,
    list_versions,
    review_prompt,
    sync_prompts,
)

router = APIRouter(prefix="/api/prompts", tags=["prompts"], dependencies=[require_section("improve")])


def _prompt_to_out(p) -> PromptOut:
    return PromptOut(
        id=str(p.id),
        integration_id=str(p.integration_id),
        external_id=p.external_id,
        name=p.name,
        template=p.template,
        version=p.version,
        variables=p.variables or [],
        metadata=p.prompt_metadata or {},
        source=p.integration.type.value if p.integration else "",
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("", response_model=PromptListResponse)
async def list_all_prompts(
    integration_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List imported prompts."""
    prompts = await list_prompts(project.id, db, integration_id=integration_id)
    items = [_prompt_to_out(p) for p in prompts]
    return PromptListResponse(data=items, total=len(items))


@router.post("/import", response_model=PromptSyncResponse)
async def import_json_prompts(
    body: PromptImportRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Import prompts from a JSON file upload."""
    if not body.prompts:
        raise HTTPException(status_code=400, detail="No prompts provided")
    count = await import_prompts_from_json(body.prompts, project.id, db)

    # Record import history
    db.add(JsonImport(
        project_id=project.id,
        entity_type="prompts",
        filename=body.filename,
        record_count=count,
    ))
    await db.commit()

    return PromptSyncResponse(synced=count, message=f"Imported {count} prompts")


@router.post("/sync/{integration_id}", response_model=PromptSyncResponse)
async def sync_integration_prompts(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Import/sync prompts from a connected platform."""
    try:
        count = await sync_prompts(integration_id, project.id, db)
        return PromptSyncResponse(synced=count, message=f"Synced {count} prompts")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{prompt_id}", response_model=PromptOut)
async def get_single_prompt(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get a prompt by ID."""
    prompt = await get_prompt(prompt_id, project.id, db)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return _prompt_to_out(prompt)


@router.get("/{prompt_id}/reviews", response_model=PromptReviewListResponse)
async def get_prompt_reviews(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List past reviews for a prompt."""
    try:
        reviews = await list_reviews(prompt_id, project.id, db)
        items = [
            PromptReviewResult(
                id=str(r.id),
                prompt_id=str(r.prompt_id),
                anti_patterns=[{"pattern": ap.get("pattern", ""), "description": ap.get("description", ""), "severity": ap.get("severity", "medium"), "location": ap.get("location", "")} for ap in (r.anti_patterns or [])],
                suggestions=r.suggestions or [],
                rewritten_prompt=r.rewritten_prompt or "",
                reviewed_at=r.reviewed_at,
                model=r.model or "",
            )
            for r in reviews
        ]
        return PromptReviewListResponse(data=items, total=len(items))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{prompt_id}/versions", response_model=PromptListResponse)
async def get_prompt_versions(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List all versions of a prompt."""
    try:
        versions = await list_versions(prompt_id, project.id, db)
        items = [_prompt_to_out(p) for p in versions]
        return PromptListResponse(data=items, total=len(items))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{prompt_id}/review", response_model=PromptReviewResult)
async def trigger_review(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Trigger LLM-based prompt review."""
    try:
        return await review_prompt(prompt_id, project.id, db, user_settings=user.settings)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Review failed: {e}")
