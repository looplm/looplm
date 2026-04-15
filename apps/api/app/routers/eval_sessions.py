"""Eval session & auto-grade endpoints.

Extracted from `eval_jobs.py` to keep file sizes manageable. Registered as a
sibling router in `evaluations.py` so URL paths and OpenAPI tags stay
identical.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user
from app.config import settings
from app.db import async_session, get_db
from app.models.models import EvalJobStatus, EvalRun, EvalSession, Experiment
from app.models.project import Project
from app.models.user import User
from app.schemas.eval_trigger import (
    EvalSessionListResponse,
    EvalSessionResponse,
    TriggerSessionRequest,
    TriggerSessionResponse,
)

from .eval_helpers import _get_eval_endpoint

router = APIRouter(tags=["evaluations"])


# ── Session Endpoints ─────────────────────────────────────────

_session_tasks: dict[UUID, asyncio.Task] = {}


@router.post("/trigger/session", response_model=TriggerSessionResponse, status_code=202)
async def trigger_session(
    body: TriggerSessionRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Trigger a session that runs multiple experiments against the same datasets."""
    from app.services.session_executor import run_session_background

    endpoint = _get_eval_endpoint(project)
    if not endpoint:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "NOT_CONFIGURED", "message": "Target API endpoint not configured. Set it in Settings → Evaluations."}},
        )

    # Validate experiments exist and belong to this project
    exp_result = await db.execute(
        select(Experiment).where(
            Experiment.id.in_(body.experiment_ids),
            Experiment.project_id == project.id,
        )
    )
    experiments = {e.id: e for e in exp_result.scalars().all()}
    missing = [str(eid) for eid in body.experiment_ids if eid not in experiments]
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": f"Experiments not found: {', '.join(missing)}"}},
        )

    concurrency = body.concurrency or settings.eval_default_concurrency
    max_turns = body.max_turns or (project.settings or {}).get("eval_max_turns") or 1

    # Build session name from experiment names
    exp_names = [experiments[eid].name for eid in body.experiment_ids]
    session_name = f"Session: {', '.join(exp_names)}"

    session = EvalSession(
        project_id=project.id,
        name=session_name,
        status=EvalJobStatus.pending,
        dataset_ids=[str(d) for d in body.dataset_ids] if body.dataset_ids else None,
        experiment_ids=[str(e) for e in body.experiment_ids],
        config={
            "concurrency": concurrency,
            "max_turns": max_turns,
        },
        progress_total=len(body.experiment_ids),
        progress_current=0,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    ps = dict(project.settings or {})
    ps["_user_settings"] = dict(user.settings or {})
    task = asyncio.create_task(
        run_session_background(
            session_id=session.id,
            project_id=project.id,
            dataset_ids=body.dataset_ids,
            experiment_ids=body.experiment_ids,
            concurrency=concurrency,
            project_settings=ps,
            max_turns=max_turns,
            use_batch=body.use_batch,
        )
    )
    _session_tasks[session.id] = task

    return TriggerSessionResponse(
        session_id=session.id,
        experiment_count=len(body.experiment_ids),
        status="pending",
    )


@router.get("/sessions", response_model=EvalSessionListResponse)
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List recent eval sessions."""
    result = await db.execute(
        select(EvalSession)
        .where(EvalSession.project_id == project.id)
        .order_by(EvalSession.started_at.desc())
        .limit(50)
    )
    sessions = result.scalars().all()

    # For each session, find linked run IDs
    data = []
    for s in sessions:
        run_result = await db.execute(
            select(EvalRun.id).where(EvalRun.session_id == s.id)
        )
        run_ids = [str(r[0]) for r in run_result.all()]
        resp = EvalSessionResponse.model_validate(s)
        resp.run_ids = run_ids
        data.append(resp)

    return EvalSessionListResponse(data=data)


@router.get("/sessions/{session_id}", response_model=EvalSessionResponse)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get session detail with linked run IDs."""
    result = await db.execute(
        select(EvalSession).where(
            EvalSession.id == session_id,
            EvalSession.project_id == project.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Eval session not found"}},
        )

    run_result = await db.execute(
        select(EvalRun.id).where(EvalRun.session_id == session.id)
    )
    run_ids = [str(r[0]) for r in run_result.all()]

    resp = EvalSessionResponse.model_validate(session)
    resp.run_ids = run_ids
    return resp


@router.post("/sessions/{session_id}/stop", status_code=200)
async def stop_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Stop a running session."""
    result = await db.execute(
        select(EvalSession).where(
            EvalSession.id == session_id,
            EvalSession.project_id == project.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Eval session not found"}},
        )
    if session.status not in (EvalJobStatus.pending, EvalJobStatus.running, EvalJobStatus.batch_pending):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "INVALID_STATE", "message": f"Cannot stop session in '{session.status}' state"}},
        )

    task = _session_tasks.pop(session_id, None)
    if task and not task.done():
        task.cancel()

    from datetime import datetime, timezone
    session.status = EvalJobStatus.cancelled
    session.completed_at = datetime.now(timezone.utc)
    await db.commit()

    return {"message": "Session cancelled", "session_id": str(session_id)}


# ── Auto-Grade Endpoints ──────────────────────────────────────

@router.post("/auto-grade/{integration_id}/start", status_code=202)
async def start_auto_grade(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Start auto-grading loop for an integration."""
    from app.services.eval_grader import start_auto_grade_loop

    await start_auto_grade_loop(integration_id, project.id, async_session)
    return {"message": "Auto-grade started", "integration_id": str(integration_id)}


@router.post("/auto-grade/{integration_id}/stop", status_code=200)
async def stop_auto_grade(
    integration_id: UUID,
    project: Project = Depends(get_current_project),
):
    """Stop auto-grading loop for an integration."""
    from app.services.eval_grader import stop_auto_grade_loop

    stop_auto_grade_loop(integration_id)
    return {"message": "Auto-grade stopped", "integration_id": str(integration_id)}
