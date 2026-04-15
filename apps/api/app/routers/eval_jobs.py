"""Evaluation job management & triggering endpoints."""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user
from app.config import settings
from app.db import async_session, get_db
from app.models.models import EvalJob, EvalJobStatus, EvalRun, EvalSession, Experiment, TestDataset
from app.models.project import Project
from app.models.user import User
from app.schemas.eval_trigger import (
    DatasetPickerItem,
    DatasetPickerResponse,
    EvalJobListResponse,
    EvalJobResponse,
    EvalSessionListResponse,
    EvalSessionResponse,
    TriggerEvalRequest,
    TriggerEvalResponse,
    TriggerSessionRequest,
    TriggerSessionResponse,
)

from .eval_helpers import (
    _get_eval_endpoint,
    _run_eval_background,
    _test_target_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["evaluations"])

_eval_tasks: dict[UUID, asyncio.Task] = {}


# ── Eval Trigger Endpoints (fixed paths — before /{run_id}) ──


@router.get("/trigger/datasets", response_model=DatasetPickerResponse)
async def list_datasets_for_trigger(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List available datasets with test counts for the eval trigger picker."""
    result = await db.execute(
        select(
            TestDataset.id,
            TestDataset.name,
            func.count(TestDataset.id).label("test_count"),
        )
        .outerjoin(TestDataset.test_cases)
        .where(TestDataset.project_id == project.id)
        .group_by(TestDataset.id)
        .order_by(TestDataset.name)
    )
    rows = result.all()
    return DatasetPickerResponse(
        datasets=[DatasetPickerItem(id=r[0], name=r[1], test_count=r[2]) for r in rows]
    )


@router.post("/trigger", response_model=TriggerEvalResponse, status_code=202)
async def trigger_eval(
    body: TriggerEvalRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Trigger a native eval run against the configured target API."""
    endpoint = _get_eval_endpoint(project)
    if not endpoint:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "NOT_CONFIGURED", "message": "Target API endpoint not configured. Set it in Settings → Evaluations."}},
        )

    # Build a label for the job
    dataset_label = "all datasets"
    if body.dataset_ids:
        ds_result = await db.execute(
            select(TestDataset.name).where(TestDataset.id.in_(body.dataset_ids))
        )
        ds_names = [r[0] for r in ds_result.all()]
        dataset_label = ", ".join(ds_names) if ds_names else f"{len(body.dataset_ids)} dataset(s)"

    concurrency = body.concurrency or settings.eval_default_concurrency
    max_turns = body.max_turns or (project.settings or {}).get("eval_max_turns") or 1

    job = EvalJob(
        project_id=project.id,
        test_suite=dataset_label,
        dataset_ids=[str(d) for d in body.dataset_ids] if body.dataset_ids else None,
        status=EvalJobStatus.pending,
        config={
            "filter_mode": body.filter_mode,
            "concurrency": concurrency,
            "max_turns": max_turns,
            "use_batch": body.use_batch,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    ps = dict(project.settings or {})
    ps["_user_settings"] = dict(user.settings or {})
    task = asyncio.create_task(
        _run_eval_background(
            job.id,
            project.id,
            body.dataset_ids,
            concurrency,
            ps,
            filter_mode=body.filter_mode,
            max_turns=max_turns,
            use_batch=body.use_batch,
        )
    )
    _eval_tasks[job.id] = task

    return TriggerEvalResponse(job_id=job.id, status="pending")


@router.post("/trigger/test-connection")
async def test_connection(
    request: Request,
    project: Project = Depends(get_current_project),
):
    """Test the target API connection with a sample prompt."""
    body = await request.json()
    result = await _test_target_connection(body, project)
    if not result.get("success") and result.get("error") == "No endpoint provided":
        raise HTTPException(status_code=400, detail="No endpoint provided")
    return result


@router.get("/jobs", response_model=EvalJobListResponse)
async def list_eval_jobs(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List recent eval jobs."""
    query = (
        select(EvalJob)
        .where(EvalJob.project_id == project.id)
        .order_by(EvalJob.started_at.desc())
        .limit(50)
    )
    if status:
        query = query.where(EvalJob.status == status)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return EvalJobListResponse(
        data=[EvalJobResponse.model_validate(j) for j in jobs]
    )


@router.post("/jobs/{job_id}/stop", status_code=200)
async def stop_eval_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Stop a running or pending eval job."""
    result = await db.execute(
        select(EvalJob).where(EvalJob.id == job_id, EvalJob.project_id == project.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Eval job not found"}},
        )
    if job.status not in (EvalJobStatus.pending, EvalJobStatus.running, EvalJobStatus.batch_pending):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "INVALID_STATE", "message": f"Cannot stop job in '{job.status}' state"}},
        )

    # Cancel the asyncio task if it exists
    task = _eval_tasks.pop(job_id, None)
    if task and not task.done():
        task.cancel()

    # Cancel batch job if in batch_pending state
    if job.status == EvalJobStatus.batch_pending and job.batch_eval_job_id:
        from app.models.models import BatchEvalJob
        batch_result = await db.execute(
            select(BatchEvalJob).where(BatchEvalJob.id == job.batch_eval_job_id)
        )
        batch_job = batch_result.scalar_one_or_none()
        if batch_job and batch_job.batch_id and batch_job.status in ("submitted", "in_progress"):
            try:
                from app.services.batch_llm_service import BatchLlmService
                batch_service = BatchLlmService()
                await batch_service.cancel_batch(batch_job.batch_id)
            except Exception as e:
                logger.warning("Failed to cancel Azure batch %s: %s", batch_job.batch_id, e)
            batch_job.status = "cancelled"

    from datetime import datetime, timezone
    job.status = EvalJobStatus.cancelled
    job.completed_at = datetime.now(timezone.utc)
    job.log = (job.log or "") + "\nJob cancelled by user."
    await db.commit()

    return {"message": "Job cancelled", "job_id": str(job_id)}


@router.post("/jobs/{job_id}/restart", response_model=TriggerEvalResponse, status_code=202)
async def restart_eval_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Restart a cancelled or failed eval job with the same parameters."""
    result = await db.execute(
        select(EvalJob).where(EvalJob.id == job_id, EvalJob.project_id == project.id)
    )
    old_job = result.scalar_one_or_none()
    if not old_job:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Eval job not found"}},
        )
    if old_job.status not in (EvalJobStatus.cancelled, EvalJobStatus.failed):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "INVALID_STATE", "message": f"Cannot restart job in '{old_job.status}' state"}},
        )

    endpoint = _get_eval_endpoint(project)
    if not endpoint:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "NOT_CONFIGURED", "message": "Target API endpoint not configured. Set it in Settings → Evaluations."}},
        )

    old_config = old_job.config or {}
    concurrency = old_config.get("concurrency", settings.eval_default_concurrency)
    filter_mode = old_config.get("filter_mode", "as_configured")
    max_turns = old_config.get("max_turns", 1)
    use_batch = old_config.get("use_batch", False)

    new_job = EvalJob(
        project_id=project.id,
        test_suite=old_job.test_suite,
        dataset_ids=old_job.dataset_ids,
        status=EvalJobStatus.pending,
        config=old_config,
    )
    db.add(new_job)
    await db.commit()
    await db.refresh(new_job)

    dataset_uuids = [UUID(d) for d in old_job.dataset_ids] if old_job.dataset_ids else None
    ps = dict(project.settings or {})
    ps["_user_settings"] = dict(user.settings or {})
    task = asyncio.create_task(
        _run_eval_background(
            new_job.id,
            project.id,
            dataset_uuids,
            concurrency,
            ps,
            filter_mode=filter_mode,
            max_turns=max_turns,
            use_batch=use_batch,
        )
    )
    _eval_tasks[new_job.id] = task

    return TriggerEvalResponse(job_id=new_job.id, status="pending")


@router.get("/jobs/{job_id}/logs")
async def get_eval_job_logs(
    job_id: UUID,
    offset: int = Query(0, ge=0, description="Line offset to return logs from"),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get just the log text for an eval job, with optional offset for incremental polling."""
    result = await db.execute(
        select(EvalJob.log).where(EvalJob.id == job_id, EvalJob.project_id == project.id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Eval job not found"}},
        )
    log = row[0] or ""
    lines = log.split("\n") if log else []
    return {
        "log": "\n".join(lines[offset:]) if offset < len(lines) else "",
        "total_lines": len(lines),
    }


@router.get("/jobs/{job_id}", response_model=EvalJobResponse)
async def get_eval_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get eval job status."""
    result = await db.execute(
        select(EvalJob).where(EvalJob.id == job_id, EvalJob.project_id == project.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Eval job not found"}},
        )
    return EvalJobResponse.model_validate(job)


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
