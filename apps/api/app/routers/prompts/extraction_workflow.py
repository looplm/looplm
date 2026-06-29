"""GitHub extraction endpoints and single-prompt CRUD.

Specific /extract/github* paths are declared before the /{prompt_id} catch-alls
so FastAPI route matching resolves them correctly.
"""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_write
from app.db import async_session, get_db
from app.models.github import GithubInstallation
from app.models.project import Project
from app.models.prompts import PromptExtraction
from app.models.user import User
from app.schemas.prompts import (
    ClusterUpdateRequest,
    ConfirmExtractionRequest,
    PromptExtractionResponse,
    PromptListResponse,
    PromptOut,
    PromptRecheckResult,
    PromptReviewListResponse,
    PromptReviewResult,
)
from app.services import github_app
from app.services.analysis_llm import merge_llm_settings
from app.services.code_agent_service import CodeAgentConfigError
from app.services.prompt_analysis import (
    add_exclusion,
    delete_prompt,
    get_prompt,
    list_reviews,
    list_versions,
    review_prompt,
)
from app.services.prompt_extraction_confirm import confirm_extraction
from app.services.prompt_extraction_maintenance import recheck_prompt
from app.services.prompt_extraction_service import (
    discover_repo_prompts,
    extract_prompts_from_repo,
)
from app.services.repo_resolver import RepoPathError, resolve_project_repo

from ._helpers import (
    _code_agent_params,
    _extraction_tasks,
    _extraction_to_out,
    _prompt_to_out,
    _resolve_repo_or_400,
)

router = APIRouter()


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
