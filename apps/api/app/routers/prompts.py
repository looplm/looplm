"""Prompt import & analysis endpoints."""

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section, require_write
from app.db import async_session, get_db
from app.models.github import GithubInstallation
from app.models.models import JsonImport
from app.models.project import Project
from app.models.prompts import PromptExtraction
from app.models.user import User
from app.schemas.prompts import (
    ClusterMoveRequest,
    ClusterMoveResult,
    ClusterUpdateRequest,
    ConfirmExtractionRequest,
    ExclusionItem,
    ExclusionListResponse,
    PlannedLocation,
    PromptExtractionResponse,
    PromptImportRequest,
    PromptListResponse,
    PromptOut,
    PromptRecheckResult,
    PromptReviewListResponse,
    PromptReviewResult,
    PromptSyncResponse,
    RemoveExclusionRequest,
)
from app.services import github_app
from app.services.analysis_llm import merge_llm_settings
from app.services.code_agent_service import CodeAgentConfigError
from app.services.prompt_analysis import (
    add_exclusion,
    delete_prompt,
    get_excluded_ids,
    get_or_create_github_integration,
    get_prompt,
    import_prompts_from_json,
    list_prompts,
    list_reviews,
    list_versions,
    remove_exclusion,
    review_prompt,
    sync_prompts,
)
from app.services.prompt_clustering import cluster_project_prompts, move_cluster
from app.services.prompt_extraction_service import (
    confirm_extraction,
    discover_repo_prompts,
    extract_prompts_from_repo,
    recheck_prompt,
)
from app.services.repo_resolver import RepoPathError, resolve_project_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompts", tags=["prompts"], dependencies=[require_section("improve", "prompts")])

_SUPPORTED_PROVIDERS = {"openai", "anthropic", "azure_openai"}
_extraction_tasks: dict[UUID, asyncio.Task] = {}


def _code_agent_params(project: Project) -> dict:
    """Resolve the Code Agent provider/model/credentials from project settings.

    Shared by GitHub extraction and per-prompt recheck — both read the repo with
    the same agent infra. Unsupported provider values fall back to 'anthropic',
    matching the Settings UI.
    """
    ps = dict(project.settings or {})
    stored = ps.get("code_agent_provider", "anthropic")
    provider = stored if stored in _SUPPORTED_PROVIDERS else "anthropic"
    if provider != stored:
        logger.warning(
            "Project %s has unsupported code_agent_provider %r; falling back to 'anthropic'",
            project.id, stored,
        )
    return {
        "provider": provider,
        "model": ps.get("code_agent_model"),
        "api_key": ps.get("code_agent_api_key"),
        "azure_endpoint": ps.get("code_agent_azure_endpoint"),
        "azure_api_version": ps.get("code_agent_azure_api_version"),
    }


def _extraction_to_out(e: PromptExtraction) -> PromptExtractionResponse:
    return PromptExtractionResponse(
        id=str(e.id),
        status=e.status,
        error=e.error,
        summary=e.summary,
        files_analyzed=e.files_analyzed or [],
        extracted_count=e.extracted_count or 0,
        total_cost_usd=e.total_cost_usd,
        num_turns=e.num_turns,
        progress_message=e.progress_message,
        progress_log=e.progress_log or [],
        planned_locations=[PlannedLocation(**loc) for loc in (e.planned_locations or [])],
        started_at=e.started_at,
        completed_at=e.completed_at,
    )


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
        cluster_path=p.cluster_path or [],
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


@router.post(
    "/{prompt_id}/review",
    response_model=PromptReviewResult,
    dependencies=[require_write("improve", "prompts")],
)
async def trigger_review(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Trigger LLM-based prompt review."""
    try:
        return await review_prompt(
            prompt_id, project.id, db,
            user_settings=merge_llm_settings(project.settings, user.settings),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Review failed: {e}")


# ── Extract prompts from a connected GitHub codebase ──────────────

@router.post(
    "/extract/github",
    status_code=202,
    dependencies=[require_write("improve", "prompts")],
)
async def trigger_github_extraction(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Kick off a background agent that extracts prompts from the connected repo."""
    # Don't start a second run while one is in flight.
    existing = await db.execute(
        select(PromptExtraction)
        .where(
            PromptExtraction.project_id == project.id,
            PromptExtraction.status.in_(["pending", "running"]),
        )
        .limit(1)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="An extraction is already running for this project.",
        )

    try:
        repo_path = await resolve_project_repo(project, db)
    except RepoPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (github_app.GithubAppDisabledError, github_app.GithubAppError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not repo_path:
        raise HTTPException(
            status_code=400,
            detail="No code repository is connected for this project. Connect one in Settings → GitHub.",
        )

    installation = (
        await db.execute(
            select(GithubInstallation).where(GithubInstallation.project_id == project.id)
        )
    ).scalar_one_or_none()
    repo_full_name = installation.repo_full_name if installation else None

    extraction = PromptExtraction(project_id=project.id, status="pending")
    db.add(extraction)
    await db.commit()
    await db.refresh(extraction)

    task = asyncio.create_task(
        extract_prompts_from_repo(
            project_id=project.id,
            extraction_id=extraction.id,
            db_factory=async_session,
            repo_path=repo_path,
            repo_full_name=repo_full_name,
            **_code_agent_params(project),
        )
    )
    _extraction_tasks[extraction.id] = task

    return {"extraction_id": str(extraction.id), "status": "pending"}


async def _resolve_repo_or_400(project: Project, db: AsyncSession) -> tuple[str, str | None]:
    """Resolve the local repo path + repo_full_name, raising HTTP errors as the
    extraction endpoints expect."""
    try:
        repo_path = await resolve_project_repo(project, db)
    except RepoPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (github_app.GithubAppDisabledError, github_app.GithubAppError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not repo_path:
        raise HTTPException(
            status_code=400,
            detail="No code repository is connected for this project. Connect one in Settings → GitHub.",
        )
    installation = (
        await db.execute(
            select(GithubInstallation).where(GithubInstallation.project_id == project.id)
        )
    ).scalar_one_or_none()
    return repo_path, (installation.repo_full_name if installation else None)


@router.post(
    "/extract/github/discover",
    status_code=202,
    dependencies=[require_write("improve", "prompts")],
)
async def discover_github_prompts(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Phase 1: discover prompt locations for the user to review before importing."""
    existing = await db.execute(
        select(PromptExtraction).where(
            PromptExtraction.project_id == project.id,
            PromptExtraction.status.in_(["pending", "discovering", "running", "clustering"]),
        ).limit(1)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An extraction is already running.")

    repo_path, repo_full_name = await _resolve_repo_or_400(project, db)

    extraction = PromptExtraction(project_id=project.id, status="pending")
    db.add(extraction)
    await db.commit()
    await db.refresh(extraction)

    task = asyncio.create_task(
        discover_repo_prompts(
            project_id=project.id, extraction_id=extraction.id, db_factory=async_session,
            repo_path=repo_path, repo_full_name=repo_full_name, **_code_agent_params(project),
        )
    )
    _extraction_tasks[extraction.id] = task
    return {"extraction_id": str(extraction.id), "status": "discovering"}


@router.post(
    "/extract/github/confirm",
    status_code=202,
    dependencies=[require_write("improve", "prompts")],
)
async def confirm_github_extraction(
    body: ConfirmExtractionRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Phase 2: extract the locations the user selected in the discovery step."""
    extraction = await db.get(PromptExtraction, UUID(body.extraction_id))
    if not extraction or extraction.project_id != project.id:
        raise HTTPException(status_code=404, detail="Extraction not found")
    if extraction.status != "awaiting_selection":
        raise HTTPException(
            status_code=409,
            detail=f"Extraction is not awaiting selection (status: {extraction.status}).",
        )

    repo_path, repo_full_name = await _resolve_repo_or_400(project, db)

    extraction.status = "pending"
    await db.commit()

    task = asyncio.create_task(
        confirm_extraction(
            project_id=project.id, extraction_id=extraction.id, db_factory=async_session,
            repo_path=repo_path, repo_full_name=repo_full_name,
            selected_external_ids=body.selected_external_ids, **_code_agent_params(project),
        )
    )
    _extraction_tasks[extraction.id] = task
    return {"extraction_id": str(extraction.id), "status": "pending"}


@router.get("/extract/github/latest", response_model=PromptExtractionResponse)
async def get_latest_github_extraction(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Return the most recent extraction run for the project (for polling)."""
    result = await db.execute(
        select(PromptExtraction)
        .where(PromptExtraction.project_id == project.id)
        .order_by(PromptExtraction.created_at.desc())
        .limit(1)
    )
    extraction = result.scalar_one_or_none()
    if not extraction:
        raise HTTPException(status_code=404, detail="No extraction has been run yet.")
    return _extraction_to_out(extraction)


@router.post(
    "/extract/github/cancel",
    dependencies=[require_write("improve", "prompts")],
)
async def cancel_github_extraction(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Cancel the running extraction for this project."""
    result = await db.execute(
        select(PromptExtraction)
        .where(
            PromptExtraction.project_id == project.id,
            PromptExtraction.status.in_(
                ["pending", "discovering", "awaiting_selection", "running", "clustering"]
            ),
        )
        .order_by(PromptExtraction.created_at.desc())
        .limit(1)
    )
    extraction = result.scalar_one_or_none()
    if not extraction:
        raise HTTPException(status_code=404, detail="No running extraction to cancel.")

    task = _extraction_tasks.pop(extraction.id, None)
    if task and not task.done():
        task.cancel()

    from datetime import datetime, timezone

    extraction.status = "cancelled"
    extraction.completed_at = datetime.now(timezone.utc)
    extraction.progress_message = None
    await db.commit()

    return {"status": "cancelled", "extraction_id": str(extraction.id)}


@router.post(
    "/{prompt_id}/recheck",
    response_model=PromptRecheckResult,
    dependencies=[require_write("improve", "prompts")],
)
async def recheck_github_prompt(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Re-extract a single github-sourced prompt from the repo to detect changes."""
    prompt = await get_prompt(prompt_id, project.id, db)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if not prompt.integration or prompt.integration.type.value != "github":
        raise HTTPException(
            status_code=400,
            detail="Only prompts extracted from GitHub can be re-checked.",
        )

    try:
        repo_path = await resolve_project_repo(project, db)
    except RepoPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (github_app.GithubAppDisabledError, github_app.GithubAppError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not repo_path:
        raise HTTPException(
            status_code=400,
            detail="No code repository is connected for this project.",
        )

    try:
        changed = await recheck_prompt(
            prompt, project_id=project.id, repo_path=repo_path, db=db,
            **_code_agent_params(project),
        )
    except (ValueError, CodeAgentConfigError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Re-check failed: {exc}") from exc

    return PromptRecheckResult(prompt=_prompt_to_out(prompt), changed=changed)


@router.patch(
    "/{prompt_id}",
    response_model=PromptOut,
    dependencies=[require_write("improve", "prompts")],
)
async def update_prompt(
    prompt_id: UUID,
    body: ClusterUpdateRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Edit a prompt's cluster assignment (move it within the hierarchy)."""
    prompt = await get_prompt(prompt_id, project.id, db)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    prompt.cluster_path = [s.strip() for s in body.cluster_path if str(s).strip()][:3]
    await db.commit()
    await db.refresh(prompt)
    return _prompt_to_out(prompt)


@router.delete("/{prompt_id}", dependencies=[require_write("improve", "prompts")])
async def remove_prompt(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Delete a prompt. Synced prompts may reappear on the next sync — use exclude
    to remove permanently."""
    ok = await delete_prompt(prompt_id, project.id, db)
    if not ok:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"status": "deleted"}


@router.post("/{prompt_id}/exclude", dependencies=[require_write("improve", "prompts")])
async def exclude_prompt(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Exclude a github prompt from sync: record its location and delete the row so
    future extractions never re-import it."""
    prompt = await get_prompt(prompt_id, project.id, db)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if not prompt.integration or prompt.integration.type.value != "github":
        raise HTTPException(
            status_code=400, detail="Only GitHub-sourced prompts can be excluded from sync."
        )
    external_id = prompt.external_id
    await add_exclusion(prompt.integration, external_id, db)
    await db.delete(prompt)
    await db.commit()
    return {"status": "excluded", "external_id": external_id}
