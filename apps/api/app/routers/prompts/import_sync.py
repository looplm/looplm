"""Prompt list/import/sync, clustering, and exclusion endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_write
from app.db import get_db
from app.models.models import JsonImport
from app.models.project import Project
from app.models.user import User
from app.schemas.prompts import (
    ClusterMoveRequest,
    ClusterMoveResult,
    ExclusionItem,
    ExclusionListResponse,
    PromptImportRequest,
    PromptListResponse,
    PromptSyncResponse,
    RemoveExclusionRequest,
)
from app.services.analysis_llm import merge_llm_settings
from app.services.prompt_analysis import (
    get_excluded_ids,
    get_or_create_github_integration,
    import_prompts_from_json,
    list_prompts,
    remove_exclusion,
    sync_prompts,
)
from app.services.prompt_clustering import cluster_project_prompts, move_cluster

from ._helpers import _prompt_to_out

router = APIRouter()


# Registered on the parent router (which carries the /api/prompts prefix) because
# FastAPI rejects an include_router sub-route whose prefix and path are both empty.
async def list_all_prompts(
    integration_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List imported prompts."""
    prompts = await list_prompts(project.id, db, integration_id=integration_id)
    items = [_prompt_to_out(p) for p in prompts]
    return PromptListResponse(data=items, total=len(items))


@router.post(
    "/import",
    response_model=PromptSyncResponse,
    dependencies=[require_write("improve", "prompts")],
)
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


@router.post(
    "/sync/{integration_id}",
    response_model=PromptSyncResponse,
    dependencies=[require_write("improve", "prompts")],
)
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


# ── Clustering & exclusions (collection-level; declared before /{prompt_id}) ──

@router.post(
    "/cluster",
    response_model=PromptSyncResponse,
    dependencies=[require_write("improve", "prompts")],
)
async def recluster_prompts(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Re-run the LLM grouping over the project's GitHub prompts."""
    try:
        count = await cluster_project_prompts(
            db, project.id, user_settings=merge_llm_settings(project.settings, user.settings)
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Clustering failed: {exc}") from exc
    return PromptSyncResponse(synced=count, message=f"Organized {count} prompts")


@router.post(
    "/clusters/move",
    response_model=ClusterMoveResult,
    dependencies=[require_write("improve", "prompts")],
)
async def move_prompt_cluster(
    body: ClusterMoveRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Bulk rename/move a cluster node (rewrite the path prefix)."""
    moved = await move_cluster(db, project.id, body.from_path, body.to_path)
    return ClusterMoveResult(moved=moved)


@router.get("/exclusions", response_model=ExclusionListResponse)
async def list_exclusions(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List source locations excluded from GitHub sync."""
    integration = await get_or_create_github_integration(project.id, db)
    items = [
        ExclusionItem(external_id=ext, name=ext.split("::", 1)[-1])
        for ext in sorted(get_excluded_ids(integration))
    ]
    await db.commit()
    return ExclusionListResponse(data=items, total=len(items))


@router.delete("/exclusions", dependencies=[require_write("improve", "prompts")])
async def delete_exclusion(
    body: RemoveExclusionRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Lift an exclusion so the location can be imported again."""
    integration = await get_or_create_github_integration(project.id, db)
    await remove_exclusion(integration, body.external_id, db)
    await db.commit()
    return {"status": "ok"}
