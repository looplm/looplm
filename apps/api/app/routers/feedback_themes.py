"""Feedback theme clustering endpoints — LLM-based clustering of feedback comments."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_write
from app.db import async_session, get_db
from app.models.models import FeedbackScore, Integration, Trace
from app.models.project import Project
from app.models.user import User
from app.routers.feedback_themes_worker import (
    _feedback_theme_tasks,
    run_feedback_themes_analysis,
)
from app.routers.top_questions import _extract_user_question
from app.schemas.feedback import (
    FeedbackTheme,
    FeedbackThemeItem,
    FeedbackThemeRequest,
    FeedbackThemesResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feedback"])


@router.post("/themes", status_code=202, dependencies=[require_write("observe", "feedback")])
async def analyze_feedback_themes(
    body: FeedbackThemeRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _user: User = Depends(get_current_user),
):
    """Start background analysis to cluster qualitative feedback comments into themes."""
    from app.models.feedback_eval import FeedbackThemeAnalysis
    from app.services.analysis_llm import (
        AnalysisLlmConfigError,
        AnalysisLlmService,
        merge_llm_settings,
    )

    # Validate LLM config early. Project-scoped settings are shared by all
    # members; a user's personal settings fill any gaps.
    llm_settings = merge_llm_settings(project.settings, _user.settings)
    try:
        AnalysisLlmService(user_settings=llm_settings)
    except AnalysisLlmConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))

    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    query = (
        select(FeedbackScore, Trace)
        .join(Trace, FeedbackScore.trace_id == Trace.id)
        .where(
            FeedbackScore.integration_id.in_(project_integration_ids),
            FeedbackScore.score_name == "user-feedback",
            FeedbackScore.comment.isnot(None),
            func.length(func.trim(FeedbackScore.comment)) > 0,
        )
    )

    if body.from_date:
        query = query.where(FeedbackScore.scored_at >= body.from_date)
    if body.to_date:
        query = query.where(FeedbackScore.scored_at <= body.to_date)
    if body.environment:
        query = query.where(Trace.trace_metadata["environment"].astext == body.environment)

    query = query.order_by(FeedbackScore.scored_at.desc()).limit(body.limit)
    result = await db.execute(query)
    rows = result.all()

    comments = []
    for feedback, trace in rows:
        comment = (feedback.comment or "").strip()
        if not comment:
            continue
        comments.append({
            "comment": comment[:500],
            "feedback_value": feedback.value,
            "feedback_id": str(feedback.id),
            "trace_id": str(feedback.trace_id) if feedback.trace_id else None,
            "question": _extract_user_question(trace.input),
        })

    if len(comments) < 5:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough commented feedback to analyze (found {len(comments)}, minimum 5).",
        )

    analysis = FeedbackThemeAnalysis(
        project_id=project.id,
        status="pending",
        total_comments=len(comments),
        filter_from_date=body.from_date,
        filter_to_date=body.to_date,
        filter_environment=body.environment,
    )
    db.add(analysis)
    await db.flush()
    await db.refresh(analysis)

    task = asyncio.create_task(
        run_feedback_themes_analysis(
            analysis_id=analysis.id,
            comments=comments,
            user_settings=llm_settings,
            db_factory=async_session,
        )
    )
    _feedback_theme_tasks[analysis.id] = task

    return {"analysis_id": str(analysis.id), "status": "pending"}


@router.get("/themes/latest", response_model=FeedbackThemesResponse)
async def get_latest_feedback_themes(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get the most recent feedback theme analysis for the project."""
    from app.models.feedback_eval import FeedbackThemeAnalysis

    result = await db.execute(
        select(FeedbackThemeAnalysis)
        .where(FeedbackThemeAnalysis.project_id == project.id)
        .order_by(FeedbackThemeAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis found")

    return _build_response(analysis)


@router.get("/themes/{analysis_id}", response_model=FeedbackThemesResponse)
async def get_feedback_themes_analysis(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get feedback theme analysis status and results."""
    from app.models.feedback_eval import FeedbackThemeAnalysis

    analysis = await db.get(FeedbackThemeAnalysis, analysis_id)
    if not analysis or analysis.project_id != project.id:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return _build_response(analysis)


@router.post(
    "/themes/{analysis_id}/stop",
    dependencies=[require_write("observe", "feedback")],
)
async def stop_feedback_themes_analysis(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Cancel an in-progress feedback theme analysis."""
    from app.models.feedback_eval import FeedbackThemeAnalysis

    analysis = await db.get(FeedbackThemeAnalysis, analysis_id)
    if not analysis or analysis.project_id != project.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if analysis.status not in ("pending", "running"):
        return {"message": "Analysis already finished", "status": analysis.status}

    task = _feedback_theme_tasks.pop(analysis_id, None)
    if task and not task.done():
        task.cancel()

    analysis.status = "cancelled"
    analysis.completed_at = datetime.now(timezone.utc)
    await db.commit()

    return {"message": "Analysis stopped", "status": "cancelled"}


def _build_response(analysis) -> FeedbackThemesResponse:
    themes = []
    if analysis.results:
        for t in analysis.results:
            all_comments = [
                FeedbackThemeItem(
                    comment=c.get("comment", ""),
                    feedback_value=c.get("feedback_value"),
                    trace_id=c.get("trace_id"),
                    question=c.get("question"),
                )
                for c in t.get("all_comments", [])
            ]
            themes.append(FeedbackTheme(
                rank=t.get("rank", 0),
                theme=t.get("theme", "Unknown"),
                count=t.get("count", 0),
                summary=t.get("summary", ""),
                all_comments=all_comments,
                feedback_sentiment=t.get("feedback_sentiment", {}),
            ))

    return FeedbackThemesResponse(
        id=analysis.id,
        status=analysis.status,
        error=analysis.error,
        total_comments=analysis.total_comments,
        processed_comments=analysis.processed_comments,
        themes=themes,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
    )
