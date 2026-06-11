"""Architecture advisor endpoints."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section, require_write
from app.db import async_session, get_db
from app.models.models import AdvisorAnalysis
from app.models.project import Project
from app.models.user import User
from app.schemas.advisor import AdvisorAnalyzeRequest, AdvisorResponse, AdvisorRunResponse
from app.services import github_app
from app.services.advisor_agent_service import analyze_architecture_with_repo, get_advisor_run
from app.services.architecture_advisor import analyze_architecture, get_latest_suggestions
from app.services.repo_resolver import RepoPathError, resolve_project_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/advisor", tags=["advisor"], dependencies=[require_section("improve", "advisor")])

_SUPPORTED_PROVIDERS = {"openai", "anthropic", "azure_openai"}

_advisor_tasks: dict[UUID, asyncio.Task] = {}


@router.post(
    "/{integration_id}/analyze",
    dependencies=[require_write("improve", "advisor")],
)
async def trigger_analysis(
    integration_id: UUID,
    body: AdvisorAnalyzeRequest | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Trigger architecture analysis.

    Without `use_repo`, runs the synchronous graph-only analysis and returns the
    suggestions directly. With `use_repo`, resolves the project's connected repo
    and launches an async agentic run; poll `GET /{integration_id}/run`.
    """
    use_repo = bool(body and body.use_repo)

    if not use_repo:
        from app.services.analysis_llm import merge_llm_settings

        try:
            return await analyze_architecture(
                integration_id, project.id, db,
                extra_context=body.extra_context if body else "",
                # Project-scoped settings are shared by all members; a user's
                # personal settings fill any gaps.
                user_settings=merge_llm_settings(project.settings, user.settings),
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

    # ── Repo-aware agentic path (async) ──────────────────────────
    ps = dict(project.settings or {})
    stored_provider = ps.get("code_agent_provider", "anthropic")
    if stored_provider in _SUPPORTED_PROVIDERS:
        provider = stored_provider
    else:
        logger.warning(
            "Project %s has unsupported code_agent_provider %r; falling back to 'anthropic'",
            project.id, stored_provider,
        )
        provider = "anthropic"

    try:
        repo_path = await resolve_project_repo(project, db)
    except RepoPathError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "INVALID_PATH", "message": str(exc)}},
        ) from exc
    except github_app.GithubAppDisabledError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "GITHUB_DISABLED", "message": str(exc)}},
        ) from exc
    except github_app.GithubAppError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "GITHUB_CLONE_FAILED", "message": str(exc)}},
        ) from exc

    if not repo_path:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "NO_REPO",
                    "message": "Connect a GitHub repository in Settings to enable repo-aware analysis.",
                }
            },
        )

    analysis = AdvisorAnalysis(
        integration_id=integration_id,
        project_id=project.id,
        status="pending",
        repo_used=True,
        analyzed_at=datetime.now(timezone.utc),
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)

    task = asyncio.create_task(
        analyze_architecture_with_repo(
            integration_id=integration_id,
            project_id=project.id,
            analysis_id=analysis.id,
            db_factory=async_session,
            repo_path=repo_path,
            extra_context=body.extra_context if body else "",
            provider=provider,
            model=ps.get("code_agent_model"),
            api_key=ps.get("code_agent_api_key"),
            azure_endpoint=ps.get("code_agent_azure_endpoint"),
            azure_api_version=ps.get("code_agent_azure_api_version"),
        )
    )
    _advisor_tasks[analysis.id] = task

    return JSONResponse(
        status_code=202,
        content={"analysis_id": str(analysis.id), "status": "pending"},
    )


@router.get("/{integration_id}/run", response_model=AdvisorRunResponse)
async def get_run(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Poll the latest async (repo-aware) advisor run for this integration."""
    result = await get_advisor_run(integration_id, project.id, db)
    if not result:
        raise HTTPException(status_code=404, detail="No advisor run found.")
    return result


@router.post("/{integration_id}/cancel", dependencies=[require_write("improve", "advisor")])
async def cancel_run(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Cancel a running repo-aware advisor analysis."""
    result = await db.execute(
        select(AdvisorAnalysis)
        .where(
            AdvisorAnalysis.integration_id == integration_id,
            AdvisorAnalysis.project_id == project.id,
            AdvisorAnalysis.status.in_(["pending", "running"]),
        )
        .order_by(AdvisorAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "No running analysis found to cancel."}},
        )

    task = _advisor_tasks.pop(analysis.id, None)
    if task and not task.done():
        task.cancel()

    analysis.status = "cancelled"
    analysis.completed_at = datetime.now(timezone.utc)
    analysis.progress_message = None
    await db.commit()

    return {"status": "cancelled", "analysis_id": str(analysis.id)}


@router.get("/{integration_id}/suggestions", response_model=AdvisorResponse)
async def get_suggestions(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    _project: Project = Depends(get_current_project),
):
    """Get latest persisted architecture suggestions."""
    result = await get_latest_suggestions(integration_id, db)
    if not result:
        raise HTTPException(status_code=404, detail="No suggestions found. Run POST /analyze first.")
    return result
