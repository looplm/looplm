"""Failure-mode analysis endpoints — LLM diagnosis + clustering of failing traces.

Clusters negative-feedback *traces* (not just their comment text) into root-cause
failure modes: retrieval miss, generation error, lost-in-the-middle / long
context, user-prompt issue, knowledge gap, refusal/formatting. Mirrors the
``feedback_themes`` triad but diagnoses each trace's full RAG context first.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_project, get_current_user, require_write
from app.db import async_session, get_db
from app.models.models import FeedbackScore, Integration, Trace
from app.models.project import Project
from app.models.user import User
from app.routers.feedback_failure_modes_worker import (
    _failure_mode_tasks,
    run_failure_mode_analysis,
    serialize_trace_for_diagnosis,
)
from app.schemas.feedback import (
    FailureModeCase,
    FailureModeCluster,
    FailureModeRequest,
    FailureModesResponse,
)
from app.services.retrieval_config import get_rag_span_names

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feedback"])

_MIN_TRACES = 2


@router.post(
    "/failure-modes", status_code=202, dependencies=[require_write("observe", "feedback")]
)
async def analyze_failure_modes(
    body: FailureModeRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _user: User = Depends(get_current_user),
):
    """Start background analysis that diagnoses and clusters failing traces."""
    from app.models.feedback_eval import FailureModeAnalysis
    from app.services.analysis_llm import (
        AnalysisLlmConfigError,
        AnalysisLlmService,
        merge_llm_settings,
    )

    # Validate LLM config early (shared project settings + personal fallbacks).
    llm_settings = merge_llm_settings(project.settings, _user.settings)
    try:
        AnalysisLlmService(user_settings=llm_settings)
    except AnalysisLlmConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if body.selected_feedback_ids is not None and len(body.selected_feedback_ids) > 200:
        raise HTTPException(status_code=400, detail="Too many selected feedback items (max 200).")

    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    query = (
        select(FeedbackScore, Trace)
        .join(Trace, FeedbackScore.trace_id == Trace.id)
        .options(selectinload(Trace.spans))
        .where(
            FeedbackScore.integration_id.in_(project_integration_ids),
            FeedbackScore.score_name == "user-feedback",
        )
    )

    if body.selected_feedback_ids:
        # Hand-pick: the selection IS the filter (the picker is where the user
        # narrows to negative feedback). Skip date/env filters and the recency cap.
        query = query.where(FeedbackScore.id.in_(body.selected_feedback_ids))
        query = query.order_by(FeedbackScore.scored_at.desc())
    else:
        # No selection: default to negative feedback only — the point of the feature.
        query = query.where(FeedbackScore.value == 0)
        if body.from_date:
            query = query.where(FeedbackScore.scored_at >= body.from_date)
        if body.to_date:
            query = query.where(FeedbackScore.scored_at <= body.to_date)
        if body.environment:
            query = query.where(Trace.trace_metadata["environment"].astext == body.environment)
        query = query.order_by(FeedbackScore.scored_at.desc()).limit(body.limit)

    result = await db.execute(query)
    rows = result.all()

    span_names = get_rag_span_names(project)
    cases: list[dict] = []
    seen_traces: set[UUID] = set()
    for feedback, trace in rows:
        # One trace can carry several feedback rows — diagnose each trace once.
        if trace.id in seen_traces:
            continue
        seen_traces.add(trace.id)
        serialized = serialize_trace_for_diagnosis(
            trace, span_names, comment=feedback.comment, feedback_value=feedback.value
        )
        cases.append({
            "trace_id": str(trace.id),
            "question": serialized["question"],
            "answer_preview": serialized["answer_preview"],
            "comment": (feedback.comment or "").strip() or None,
            "feedback_value": feedback.value,
            "serialized": serialized["serialized"],
        })

    if len(cases) < _MIN_TRACES:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough traces to analyze (found {len(cases)}, minimum {_MIN_TRACES}).",
        )

    analysis = FailureModeAnalysis(
        project_id=project.id,
        status="pending",
        total_traces=len(cases),
        filter_from_date=body.from_date,
        filter_to_date=body.to_date,
        filter_environment=body.environment,
        filter_selected_feedback_ids=(
            [str(i) for i in body.selected_feedback_ids] if body.selected_feedback_ids else None
        ),
    )
    db.add(analysis)
    # Commit before launching the task: the worker reads this row from its own
    # session, where an uncommitted row is invisible.
    await db.commit()
    await db.refresh(analysis)

    task = asyncio.create_task(
        run_failure_mode_analysis(
            analysis_id=analysis.id,
            cases=cases,
            user_settings=llm_settings,
            db_factory=async_session,
        )
    )
    _failure_mode_tasks[analysis.id] = task

    return {"analysis_id": str(analysis.id), "status": "pending"}


@router.get("/failure-modes/latest", response_model=FailureModesResponse)
async def get_latest_failure_modes(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get the most recent failure-mode analysis for the project."""
    from app.models.feedback_eval import FailureModeAnalysis

    result = await db.execute(
        select(FailureModeAnalysis)
        .where(FailureModeAnalysis.project_id == project.id)
        .order_by(FailureModeAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis found")

    return _build_response(analysis)


@router.get("/failure-modes/{analysis_id}", response_model=FailureModesResponse)
async def get_failure_mode_analysis(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get failure-mode analysis status and results."""
    from app.models.feedback_eval import FailureModeAnalysis

    analysis = await db.get(FailureModeAnalysis, analysis_id)
    if not analysis or analysis.project_id != project.id:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return _build_response(analysis)


@router.post(
    "/failure-modes/{analysis_id}/stop",
    dependencies=[require_write("observe", "feedback")],
)
async def stop_failure_mode_analysis(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Cancel an in-progress failure-mode analysis."""
    from app.models.feedback_eval import FailureModeAnalysis

    analysis = await db.get(FailureModeAnalysis, analysis_id)
    if not analysis or analysis.project_id != project.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if analysis.status not in ("pending", "running"):
        return {"message": "Analysis already finished", "status": analysis.status}

    task = _failure_mode_tasks.pop(analysis_id, None)
    if task and not task.done():
        task.cancel()

    analysis.status = "cancelled"
    analysis.completed_at = datetime.now(timezone.utc)
    await db.commit()

    return {"message": "Analysis stopped", "status": "cancelled"}


def _build_response(analysis) -> FailureModesResponse:
    clusters = []
    for c in analysis.results or []:
        cases = [
            FailureModeCase(
                trace_id=case.get("trace_id"),
                question=case.get("question"),
                answer_preview=case.get("answer_preview"),
                comment=case.get("comment"),
                feedback_value=case.get("feedback_value"),
                category=case.get("category", "other"),
                explanation=case.get("explanation", ""),
                confidence=case.get("confidence"),
            )
            for case in c.get("cases", [])
        ]
        clusters.append(FailureModeCluster(
            rank=c.get("rank", 0),
            label=c.get("label", "Unlabeled"),
            category=c.get("category", "other"),
            count=c.get("count", 0),
            description=c.get("description", ""),
            recommendation=c.get("recommendation", ""),
            category_counts=c.get("category_counts", {}),
            cases=cases,
        ))

    return FailureModesResponse(
        id=analysis.id,
        status=analysis.status,
        error=analysis.error,
        total_traces=analysis.total_traces,
        processed_traces=analysis.processed_traces,
        clusters=clusters,
        category_counts=analysis.category_counts or {},
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
    )
