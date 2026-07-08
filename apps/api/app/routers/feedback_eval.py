"""Feedback evaluation endpoints."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_write
from app.db import async_session, get_db
from app.models.models import FeedbackScore, Integration, Trace
from app.models.project import Project
from app.models.user import User
from app.routers.feedback_eval_worker import (
    FEEDBACK_EVAL_SYSTEM_PROMPT,
    _feedback_eval_tasks,
    run_feedback_evaluation,
)
from app.schemas.feedback import (
    FeedbackEvalItem,
    FeedbackEvalSummary,
    FeedbackEvaluateRequest,
    FeedbackEvaluateResponse,
    FeedbackEvaluatorConfigResponse,
    FeedbackEvaluatorConfigUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feedback"])


@router.post("/evaluate-single/{feedback_id}", dependencies=[require_write("observe", "feedback")])
async def evaluate_single_feedback(
    feedback_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _user: User = Depends(get_current_user),
):
    """Evaluate a single feedback item synchronously."""
    import json
    import re

    from app.routers.dataset_helpers import _extract_answer, _extract_user_prompt
    from app.models.feedback_eval import FeedbackEvalResult, FeedbackEvaluatorConfig
    from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService

    try:
        llm_service = AnalysisLlmService(
            user_settings=_user.settings, project_settings=project.settings
        )
    except AnalysisLlmConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Load feedback + trace
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    result = await db.execute(
        select(FeedbackScore, Trace)
        .join(Trace, FeedbackScore.trace_id == Trace.id)
        .where(FeedbackScore.id == feedback_id, FeedbackScore.integration_id.in_(project_integration_ids))
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Feedback not found")

    feedback, trace = row
    user_question = _extract_user_prompt(trace.input)
    llm_answer = _extract_answer(trace.output)
    if not user_question and not llm_answer:
        raise HTTPException(status_code=400, detail="No question/answer found in trace")

    # Load evaluator config
    config_result = await db.execute(
        select(FeedbackEvaluatorConfig).where(FeedbackEvaluatorConfig.project_id == project.id)
    )
    eval_config = config_result.scalar_one_or_none()
    prompt = eval_config.prompt if eval_config else FEEDBACK_EVAL_SYSTEM_PROMPT
    valid_verdicts = set(eval_config.verdicts) if eval_config else {"suspicious", "helpful", "unhelpful"}
    fallback_verdict = eval_config.default_verdict if eval_config else "unhelpful"

    # Build item with metadata
    metadata = {}
    if trace.trace_metadata:
        for key in ("model", "userName", "teamFilter", "environment", "operation",
                    "hasRAG", "messageCount", "searchResultCount", "tagFilter"):
            if key in trace.trace_metadata:
                metadata[key] = trace.trace_metadata[key]

    item = {
        "feedback_id": str(feedback.id),
        "value": feedback.value,
        "comment": feedback.comment,
        "user_question": (user_question or "")[:500],
        "llm_answer": (llm_answer or "")[:1000],
        **({"metadata": metadata} if metadata else {}),
    }

    # Single LLM call
    user_content = json.dumps([item], indent=2, default=str)
    try:
        from app.services.llm_usage_tracker import record_llm_usage

        text, usage = await llm_service.tracked_chat_completion(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
        )

        await record_llm_usage(
            db,
            project_id=project.id,
            service_name="feedback_eval",
            function_name="evaluate_single_feedback",
            provider=llm_service.provider,
            model=llm_service.model,
            usage=usage,
            request_metadata={"feedback_id": str(feedback_id)},
        )

        try:
            results = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
            results = json.loads(match.group(1)) if match else []
    except HTTPException:
        raise
    except Exception:
        logger.exception("Single feedback evaluation failed")
        raise HTTPException(status_code=500, detail="LLM evaluation failed")

    if not results:
        raise HTTPException(status_code=500, detail="LLM returned no results")

    r = results[0]
    verdict = r.get("verdict", fallback_verdict)
    if verdict not in valid_verdicts:
        verdict = fallback_verdict
    confidence = min(max(float(r.get("confidence", 0.5)), 0.0), 1.0)
    reasoning = r.get("reasoning", "")

    # Persist result
    db.add(FeedbackEvalResult(
        feedback_id=feedback.id,
        trace_id=feedback.trace_id,
        score_name=feedback.score_name,
        value=feedback.value,
        comment=feedback.comment,
        trace_input_preview=(user_question or "")[:200] or None,
        verdict=verdict,
        reasoning=reasoning,
        confidence=confidence,
    ))
    await db.commit()

    return {
        "verdict": verdict,
        "reasoning": reasoning,
        "confidence": confidence,
    }


@router.post("/evaluate", status_code=202, dependencies=[require_write("observe", "feedback")])
async def evaluate_feedback(
    body: FeedbackEvaluateRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _user: User = Depends(get_current_user),
):
    """Start background evaluation of feedback quality."""
    from app.routers.dataset_helpers import _extract_answer, _extract_user_prompt
    from app.models.feedback_eval import FeedbackEvaluation, FeedbackEvaluatorConfig
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

    # Load feedback evaluator config for this project (if configured)
    config_result = await db.execute(
        select(FeedbackEvaluatorConfig).where(FeedbackEvaluatorConfig.project_id == project.id)
    )
    eval_config = config_result.scalar_one_or_none()

    from app.models.feedback_eval import FeedbackEvalResult

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

    # Skip already-evaluated items unless reevaluate is requested
    if not body.reevaluate:
        already_evaluated = select(FeedbackEvalResult.feedback_id).distinct()
        query = query.where(FeedbackScore.id.not_in(already_evaluated))

    query = query.order_by(FeedbackScore.scored_at.desc()).limit(body.limit)
    result = await db.execute(query)
    rows = result.all()

    # Build items for LLM evaluation
    eval_items = []
    for feedback, trace in rows:
        user_question = _extract_user_prompt(trace.input)
        llm_answer = _extract_answer(trace.output)
        if not user_question and not llm_answer:
            continue
        # Include trace metadata for richer LLM context
        metadata = {}
        if trace and trace.trace_metadata:
            for key in ("model", "userName", "teamFilter", "environment", "operation",
                        "hasRAG", "messageCount", "searchResultCount", "tagFilter"):
                if key in trace.trace_metadata:
                    metadata[key] = trace.trace_metadata[key]

        eval_items.append({
            "feedback_id": str(feedback.id),
            "trace_id": str(feedback.trace_id) if feedback.trace_id else None,
            "score_name": feedback.score_name,
            "value": feedback.value,
            "comment": feedback.comment,
            "user_question": (user_question or "")[:500],
            "llm_answer": (llm_answer or "")[:1000],
            **({"metadata": metadata} if metadata else {}),
        })

    # Create evaluation record
    evaluation = FeedbackEvaluation(
        project_id=project.id,
        status="pending",
        total_count=len(eval_items),
    )
    db.add(evaluation)
    await db.flush()
    await db.refresh(evaluation)
    # Commit before launching the task: the worker reads this record from a
    # separate session, so it must be visible. Without this the request's
    # deferred get_db commit can race the worker's first read, which returns
    # None and silently kills the task — leaving the run stuck on "pending".
    await db.commit()

    # Launch background task
    task = asyncio.create_task(
        run_feedback_evaluation(
            evaluation_id=evaluation.id,
            eval_items=eval_items,
            user_settings=llm_settings,
            db_factory=async_session,
            system_prompt=eval_config.prompt if eval_config else None,
            verdicts=eval_config.verdicts if eval_config else None,
            default_verdict=eval_config.default_verdict if eval_config else None,
        )
    )
    _feedback_eval_tasks[evaluation.id] = task

    return {"evaluation_id": str(evaluation.id), "status": "pending"}


@router.post("/evaluate/{evaluation_id}/stop", dependencies=[require_write("observe", "feedback")])
async def stop_feedback_evaluation(
    evaluation_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Stop a running feedback evaluation."""
    from app.models.feedback_eval import FeedbackEvaluation

    evaluation = await db.get(FeedbackEvaluation, evaluation_id)
    if not evaluation or evaluation.project_id != project.id:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    if evaluation.status not in ("pending", "running"):
        return {"message": "Evaluation already finished", "status": evaluation.status}

    # Cancel the background task
    task = _feedback_eval_tasks.pop(evaluation_id, None)
    if task and not task.done():
        task.cancel()

    evaluation.status = "cancelled"
    evaluation.completed_at = datetime.utcnow()
    await db.commit()

    return {"message": "Evaluation stopped", "status": "cancelled"}


@router.get("/evaluate/{evaluation_id}", response_model=FeedbackEvaluateResponse)
async def get_feedback_evaluation(
    evaluation_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get feedback evaluation status and results."""
    from sqlalchemy.orm import selectinload

    from app.models.feedback_eval import FeedbackEvaluation

    result = await db.execute(
        select(FeedbackEvaluation)
        .options(selectinload(FeedbackEvaluation.results))
        .where(
            FeedbackEvaluation.id == evaluation_id,
            FeedbackEvaluation.project_id == project.id,
        )
    )
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Evaluation not found"}},
        )

    items = [
        FeedbackEvalItem(
            feedback_id=r.feedback_id,
            trace_id=r.trace_id,
            score_name=r.score_name,
            value=r.value,
            comment=r.comment,
            trace_input_preview=r.trace_input_preview,
            verdict=r.verdict,
            reasoning=r.reasoning,
            confidence=r.confidence,
        )
        for r in evaluation.results
    ]

    # Build verdict_counts: prefer stored JSONB, fall back to legacy columns
    verdict_counts = evaluation.verdict_counts or {}
    if not verdict_counts:
        verdict_counts = {
            "suspicious": evaluation.suspicious_count,
            "helpful": evaluation.helpful_count,
            "unhelpful": evaluation.unhelpful_count,
        }

    return FeedbackEvaluateResponse(
        id=evaluation.id,
        status=evaluation.status,
        error=evaluation.error,
        summary=FeedbackEvalSummary(
            total_count=evaluation.total_count,
            evaluated_count=evaluation.evaluated_count,
            suspicious_count=evaluation.suspicious_count,
            helpful_count=evaluation.helpful_count,
            unhelpful_count=evaluation.unhelpful_count,
            verdict_counts=verdict_counts,
        ),
        items=items,
        started_at=evaluation.started_at,
        completed_at=evaluation.completed_at,
    )


# --- Feedback Evaluator Config ---


@router.get("/evaluator/config", response_model=FeedbackEvaluatorConfigResponse)
async def get_feedback_evaluator_config(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get the feedback evaluator config for the current project. Auto-creates with defaults if missing."""
    from app.models.feedback_eval import FeedbackEvaluatorConfig

    result = await db.execute(
        select(FeedbackEvaluatorConfig).where(FeedbackEvaluatorConfig.project_id == project.id)
    )
    config = result.scalar_one_or_none()

    if not config:
        config = FeedbackEvaluatorConfig(
            project_id=project.id,
            prompt=FEEDBACK_EVAL_SYSTEM_PROMPT,
            verdicts=["suspicious", "helpful", "unhelpful"],
            default_verdict="unhelpful",
        )
        db.add(config)
        await db.flush()
        await db.refresh(config)

    return config


@router.put(
    "/evaluator/config",
    response_model=FeedbackEvaluatorConfigResponse,
    dependencies=[require_write("observe", "feedback")],
)
async def update_feedback_evaluator_config(
    body: FeedbackEvaluatorConfigUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _user: User = Depends(get_current_user),
):
    """Update the feedback evaluator config for the current project."""
    from app.models.feedback_eval import FeedbackEvaluatorConfig

    result = await db.execute(
        select(FeedbackEvaluatorConfig).where(FeedbackEvaluatorConfig.project_id == project.id)
    )
    config = result.scalar_one_or_none()

    if not config:
        config = FeedbackEvaluatorConfig(
            project_id=project.id,
            prompt=FEEDBACK_EVAL_SYSTEM_PROMPT,
            verdicts=["suspicious", "helpful", "unhelpful"],
            default_verdict="unhelpful",
        )
        db.add(config)
        await db.flush()

    if body.prompt is not None:
        config.prompt = body.prompt
    if body.verdicts is not None:
        if len(body.verdicts) < 1:
            raise HTTPException(status_code=400, detail="At least one verdict is required")
        config.verdicts = body.verdicts
    if body.default_verdict is not None:
        current_verdicts = body.verdicts if body.verdicts is not None else config.verdicts
        if body.default_verdict not in current_verdicts:
            raise HTTPException(
                status_code=400,
                detail=f"default_verdict '{body.default_verdict}' must be one of the configured verdicts",
            )
        config.default_verdict = body.default_verdict
    if body.model is not None:
        config.model = body.model or None

    config.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(config)
    return config
