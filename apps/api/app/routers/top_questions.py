"""Top questions analysis endpoints — LLM-based question clustering."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_write
from app.db import async_session, get_db
from app.models.models import FeedbackScore, Integration, Trace
from app.models.project import Project
from app.models.user import User
from app.routers.top_questions_worker import (
    _top_questions_tasks,
    run_top_questions_analysis,
)
from app.schemas.feedback import (
    TopQuestionTheme,
    TopQuestionsRequest,
    TopQuestionsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feedback"])


def _extract_user_question(trace_input) -> str | None:
    """Extract last user message from trace input, handling multiple formats."""
    if not trace_input:
        return None
    # Plain string
    if isinstance(trace_input, str):
        return trace_input if trace_input.strip() else None
    # Array of messages (Vercel AI SDK without wrapper)
    if isinstance(trace_input, list):
        for msg in reversed(trace_input):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            return part.get("text", "")
        return None
    # Dict with messages key
    if isinstance(trace_input, dict):
        messages = trace_input.get("messages")
        if isinstance(messages, list):
            return _extract_user_question(messages)
        # Fallback: try common keys
        for key in ("text", "content", "query", "question", "input"):
            val = trace_input.get(key)
            if isinstance(val, str) and val.strip():
                return val
    return None


@router.post("/top-questions", status_code=202, dependencies=[require_write("observe", "feedback")])
async def analyze_top_questions(
    body: TopQuestionsRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _user: User = Depends(get_current_user),
):
    """Start background analysis to identify top question themes from feedback."""
    from app.models.feedback_eval import TopQuestionsAnalysis
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

    # Extract questions
    questions = []
    for feedback, trace in rows:
        user_question = _extract_user_question(trace.input)
        if not user_question:
            continue
        questions.append({
            "question": user_question[:300],
            "feedback_value": feedback.value,
            "feedback_id": str(feedback.id),
            "trace_id": str(feedback.trace_id) if feedback.trace_id else None,
        })

    if len(questions) < 5:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough questions to analyze (found {len(questions)}, minimum 5).",
        )

    # Create analysis record
    analysis = TopQuestionsAnalysis(
        project_id=project.id,
        status="pending",
        total_questions=len(questions),
        filter_from_date=body.from_date,
        filter_to_date=body.to_date,
        filter_environment=body.environment,
    )
    db.add(analysis)
    await db.flush()
    await db.refresh(analysis)

    # Launch background task
    task = asyncio.create_task(
        run_top_questions_analysis(
            analysis_id=analysis.id,
            questions=questions,
            user_settings=llm_settings,
            db_factory=async_session,
        )
    )
    _top_questions_tasks[analysis.id] = task

    return {"analysis_id": str(analysis.id), "status": "pending"}


@router.get("/top-questions/latest", response_model=TopQuestionsResponse)
async def get_latest_top_questions(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get the most recent top questions analysis for the project."""
    from app.models.feedback_eval import TopQuestionsAnalysis

    result = await db.execute(
        select(TopQuestionsAnalysis)
        .where(TopQuestionsAnalysis.project_id == project.id)
        .order_by(TopQuestionsAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis found")

    return _build_response(analysis)


@router.get("/top-questions/{analysis_id}", response_model=TopQuestionsResponse)
async def get_top_questions_analysis(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get top questions analysis status and results."""
    from app.models.feedback_eval import TopQuestionsAnalysis

    analysis = await db.get(TopQuestionsAnalysis, analysis_id)
    if not analysis or analysis.project_id != project.id:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return _build_response(analysis)


@router.post(
    "/top-questions/{analysis_id}/stop",
    dependencies=[require_write("observe", "feedback")],
)
async def stop_top_questions_analysis(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Cancel an in-progress top questions analysis."""
    from app.models.feedback_eval import TopQuestionsAnalysis

    analysis = await db.get(TopQuestionsAnalysis, analysis_id)
    if not analysis or analysis.project_id != project.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if analysis.status not in ("pending", "running"):
        return {"message": "Analysis already finished", "status": analysis.status}

    # Cancel the background task
    task = _top_questions_tasks.pop(analysis_id, None)
    if task and not task.done():
        task.cancel()

    analysis.status = "cancelled"
    analysis.completed_at = datetime.now(timezone.utc)
    await db.commit()

    return {"message": "Analysis stopped", "status": "cancelled"}


def _build_response(analysis) -> TopQuestionsResponse:
    from app.schemas.feedback import TopQuestionItem

    themes = []
    if analysis.results:
        for t in analysis.results:
            all_questions = [
                TopQuestionItem(
                    question=q.get("question", ""),
                    feedback_value=q.get("feedback_value"),
                    trace_id=q.get("trace_id"),
                )
                for q in t.get("all_questions", [])
            ]
            themes.append(TopQuestionTheme(
                rank=t.get("rank", 0),
                theme=t.get("theme", "Unknown"),
                count=t.get("count", 0),
                summary_question=t.get("summary_question", ""),
                all_questions=all_questions,
                feedback_sentiment=t.get("feedback_sentiment", {}),
            ))

    return TopQuestionsResponse(
        id=analysis.id,
        status=analysis.status,
        error=analysis.error,
        total_questions=analysis.total_questions,
        processed_questions=analysis.processed_questions,
        themes=themes,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
    )
