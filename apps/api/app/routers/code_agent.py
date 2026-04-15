"""Code Agent endpoints — eval-driven code suggestions via Claude Agent SDK."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section
from app.db import async_session, get_db
from app.models.evaluations import EvalRun
from app.models.code_agent import OpenCodeAnalysis
from app.models.project import Project
from app.models.user import User
from app.schemas.code_agent import (
    CodeSuggestionItem,
    CodeSuggestionStatusUpdate,
    OpenCodeAnalysisResponse,
    TriggerOpenCodeRequest,
)
from app.services.code_agent_service import (
    analyze_eval_run,
    get_analysis,
    update_suggestion_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/code-agent", tags=["code-agent"], dependencies=[require_section("improve")])

_code_agent_tasks: dict[UUID, asyncio.Task] = {}


@router.post("/{eval_run_id}/analyze", status_code=202)
async def trigger_code_agent_analysis(
    eval_run_id: UUID,
    body: TriggerOpenCodeRequest | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Trigger Code Agent analysis for an eval run."""
    # Validate eval run exists and belongs to project
    result = await db.execute(
        select(EvalRun).where(
            EvalRun.id == eval_run_id, EvalRun.project_id == project.id
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Eval run not found"}},
        )

    # Resolve repo path (optional)
    ps = dict(project.settings or {})
    repo_path = ps.get("code_agent_repo_path")
    if repo_path:
        p = Path(repo_path)
        if not p.exists() or not p.is_dir():
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "INVALID_PATH",
                        "message": f"Repository path does not exist or is not a directory: {repo_path}",
                    }
                },
            )

    file_patterns = (
        (body.file_patterns if body and body.file_patterns else None)
        or ps.get("code_agent_file_patterns")
    )

    mode = (body.analysis_mode if body else "detailed") or "detailed"

    # Create analysis record
    analysis = OpenCodeAnalysis(
        project_id=project.id,
        eval_run_id=eval_run_id,
        status="pending",
        analysis_mode=mode,
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)

    # Launch background task
    task = asyncio.create_task(
        analyze_eval_run(
            project_id=project.id,
            eval_run_id=eval_run_id,
            analysis_id=analysis.id,
            db_factory=async_session,
            repo_path=repo_path,
            extra_context=body.extra_context if body else "",
            file_patterns=file_patterns,
            provider=ps.get("code_agent_provider", "anthropic"),
            model=ps.get("code_agent_model"),
            api_key=ps.get("code_agent_api_key"),
            foundry_resource=ps.get("code_agent_foundry_resource"),
            mode=mode,
        )
    )
    _code_agent_tasks[analysis.id] = task

    return {"analysis_id": str(analysis.id), "status": "pending"}


@router.get("/{eval_run_id}/analysis", response_model=OpenCodeAnalysisResponse)
async def get_code_agent_analysis(
    eval_run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get the latest Code Agent analysis for an eval run."""
    result = await get_analysis(eval_run_id, project.id, db)
    if not result:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "No analysis found. Trigger one with POST first.",
                }
            },
        )
    return result


@router.post("/{eval_run_id}/cancel")
async def cancel_code_agent_analysis(
    eval_run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Cancel a running Code Agent analysis."""
    # Find the latest pending/running analysis for this eval run
    result = await db.execute(
        select(OpenCodeAnalysis)
        .where(
            OpenCodeAnalysis.eval_run_id == eval_run_id,
            OpenCodeAnalysis.project_id == project.id,
            OpenCodeAnalysis.status.in_(["pending", "running"]),
        )
        .order_by(OpenCodeAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "No running analysis found to cancel.",
                }
            },
        )

    # Cancel the asyncio task if it exists
    task = _code_agent_tasks.pop(analysis.id, None)
    if task and not task.done():
        task.cancel()

    # Update status in DB (task cancel handler will also try, but this is a safety net)
    from datetime import datetime, timezone

    analysis.status = "cancelled"
    analysis.completed_at = datetime.now(timezone.utc)
    analysis.progress_message = None
    await db.commit()

    return {"status": "cancelled", "analysis_id": str(analysis.id)}


@router.patch("/suggestions/{suggestion_id}", response_model=CodeSuggestionItem)
async def patch_suggestion_status(
    suggestion_id: UUID,
    body: CodeSuggestionStatusUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Update a code suggestion's status (applied/dismissed)."""
    if body.status not in ("applied", "dismissed"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_STATUS",
                    "message": "Status must be 'applied' or 'dismissed'",
                }
            },
        )
    result = await update_suggestion_status(suggestion_id, project.id, body.status, db)
    if not result:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Suggestion not found"}},
        )
    return result
