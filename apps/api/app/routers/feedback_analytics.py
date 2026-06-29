"""Feedback analytics and suggestion endpoints."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_write
from app.db import get_db
from app.models.models import FeedbackScore, Integration, Trace
from app.models.project import Project
from app.models.user import User
from app.services.feedback_stats_service import compute_feedback_stats
from app.services.observe_filter import get_observe_trace_names
from app.services.retrieval_config import get_retrieval_span_name
from app.schemas.feedback import (
    FeedbackStatsResponse,
    RegenerateExpectedAnswerResponse,
    SuggestionRunResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feedback"])


@router.get("/stats", response_model=FeedbackStatsResponse)
async def feedback_stats(
    days: int = Query(30, ge=1, le=365),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    environment: str | None = None,
    include_user_ids: str | None = None,
    exclude_user_ids: str | None = None,
    integration_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    return await compute_feedback_stats(
        db,
        project,
        days=days,
        start_date=start_date,
        end_date=end_date,
        environment=environment,
        include_user_ids=include_user_ids,
        exclude_user_ids=exclude_user_ids,
        integration_id=integration_id,
    )


def _build_suggestion_run_response(run) -> SuggestionRunResponse:
    return SuggestionRunResponse(
        id=run.id,
        status=run.status,
        error=run.error,
        total=run.total or 0,
        processed=run.processed or 0,
        count=run.count or 0,
        source_feedback_count=run.source_feedback_count or 0,
        suggestions=run.suggestions or [],
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


@router.post(
    "/generate-suggestions",
    response_model=SuggestionRunResponse,
    status_code=202,
    dependencies=[require_write("observe", "feedback")],
)
async def generate_suggestions(
    feedback_type: str = Query("all", pattern="^(positive|negative|all)$"),
    limit: int = Query(20, ge=1, le=100),
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    environment: str | None = None,
    include_user_ids: str | None = None,
    exclude_user_ids: str | None = None,
    selected_feedback_ids: str | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _user: User = Depends(get_current_user),
):
    """Kick off background generation of LLM-enhanced test case suggestions.

    Returns a run record the frontend can poll. Only feedback rows linked to a
    trace are considered. Honors the project's Observe trace-name filter and
    optional date/environment/user filters.

    When ``selected_feedback_ids`` is given, only those feedback rows are used
    and the date/environment/user/type filters and recency limit are skipped —
    an explicit hand-pick takes precedence over the auto "most recent" path.
    """
    from app.db import async_session
    from app.models.feedback_eval import FeedbackSuggestionRun
    from app.routers.dataset_helpers import (
        build_suggestions,
        load_trace_conversation_messages,
        load_trace_source_urls,
    )
    from app.routers.feedback_suggestion_worker import (
        _suggestion_tasks,
        run_suggestion_generation,
    )
    from app.services.analysis_llm import merge_llm_settings

    # Project-scoped settings are shared by all members; a user's personal
    # settings fill any gaps.
    llm_settings = merge_llm_settings(project.settings, _user.settings)

    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    selected_ids: list[UUID] = []
    if selected_feedback_ids:
        raw_ids = [v.strip() for v in selected_feedback_ids.split(",") if v.strip()]
        if len(raw_ids) > 200:
            raise HTTPException(
                status_code=400,
                detail="Too many selected feedback items (max 200).",
            )
        try:
            selected_ids = [UUID(v) for v in raw_ids]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid feedback id in selection.")

    query = (
        select(FeedbackScore, Trace)
        .join(Trace, FeedbackScore.trace_id == Trace.id)
        .where(
            FeedbackScore.integration_id.in_(project_integration_ids),
            FeedbackScore.score_name == "user-feedback",
        )
    )

    observe_names = get_observe_trace_names(project)
    if observe_names:
        query = query.where(Trace.name.in_(observe_names))

    inc_uids = [v.strip() for v in (include_user_ids or "").split(",") if v.strip()]
    exc_uids = [v.strip() for v in (exclude_user_ids or "").split(",") if v.strip()]

    if selected_ids:
        # Explicit hand-pick: the selection IS the filter. Skip the
        # type/date/environment/user filters and the recency cap.
        query = query.where(FeedbackScore.id.in_(selected_ids))
        query = query.order_by(FeedbackScore.scored_at.desc())
    else:
        if feedback_type == "positive":
            query = query.where(FeedbackScore.value == 1)
        elif feedback_type == "negative":
            query = query.where(FeedbackScore.value == 0)

        if from_date:
            query = query.where(FeedbackScore.scored_at >= from_date)
        if to_date:
            query = query.where(FeedbackScore.scored_at <= to_date)
        if environment:
            query = query.where(Trace.trace_metadata["environment"].astext == environment)

        if inc_uids:
            query = query.where(Trace.user_id.in_(inc_uids))
        if exc_uids:
            query = query.where(~Trace.user_id.in_(exc_uids))

        query = query.order_by(FeedbackScore.scored_at.desc()).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    trace_ids = [trace.id for _fb, trace in rows if trace is not None]
    trace_sources = await load_trace_source_urls(
        db, trace_ids, get_retrieval_span_name(project)
    )
    trace_messages = await load_trace_conversation_messages(db, trace_ids)
    suggestions = build_suggestions(rows, trace_sources=trace_sources)

    feedback_comments: dict[str, str | None] = {}
    feedback_messages: dict[str, list[dict[str, str]]] = {}
    for feedback, trace in rows:
        feedback_comments[str(feedback.id)] = feedback.comment
        if trace is not None:
            feedback_messages[str(feedback.id)] = trace_messages.get(str(trace.id), [])
    for sug in suggestions:
        sug.comment = feedback_comments.get(str(sug.feedback_id))

    if not suggestions:
        raise HTTPException(
            status_code=400,
            detail="No suggestions could be built from feedback in the current filter range.",
        )

    # Progress total now covers every suggestion: each one may need a context
    # summary, and negatives additionally need criteria. Single-turn
    # suggestions complete immediately, but counting them keeps the bar truthful.
    total_steps = len(suggestions)

    run = FeedbackSuggestionRun(
        project_id=project.id,
        status="pending",
        feedback_type=feedback_type,
        filter_from_date=from_date,
        filter_to_date=to_date,
        filter_environment=environment,
        filter_include_user_ids=inc_uids or None,
        filter_exclude_user_ids=exc_uids or None,
        filter_selected_feedback_ids=[str(i) for i in selected_ids] or None,
        filter_limit=limit,
        source_feedback_count=len(rows),
        total=total_steps,
        processed=0,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    await db.commit()

    task = asyncio.create_task(
        run_suggestion_generation(
            run_id=run.id,
            project_id=project.id,
            suggestions=suggestions,
            feedback_comments=feedback_comments,
            feedback_messages=feedback_messages,
            user_settings=llm_settings,
            db_factory=async_session,
        )
    )
    _suggestion_tasks[run.id] = task

    return _build_suggestion_run_response(run)


@router.get(
    "/generate-suggestions/latest",
    response_model=SuggestionRunResponse,
)
async def get_latest_suggestions(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Return the most recent suggestion run for the current project.

    404 if nothing has ever been generated — the frontend treats that as the
    "click Generate" empty state.
    """
    from app.models.feedback_eval import FeedbackSuggestionRun

    result = await db.execute(
        select(FeedbackSuggestionRun)
        .where(FeedbackSuggestionRun.project_id == project.id)
        .order_by(FeedbackSuggestionRun.created_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="No suggestion run found")
    return _build_suggestion_run_response(run)


@router.get(
    "/generate-suggestions/{run_id}",
    response_model=SuggestionRunResponse,
)
async def get_suggestion_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get a specific suggestion run for polling progress."""
    from app.models.feedback_eval import FeedbackSuggestionRun

    run = await db.get(FeedbackSuggestionRun, run_id)
    if not run or run.project_id != project.id:
        raise HTTPException(status_code=404, detail="Suggestion run not found")
    return _build_suggestion_run_response(run)


@router.post(
    "/generate-suggestions/{run_id}/stop",
    response_model=SuggestionRunResponse,
    dependencies=[require_write("observe", "feedback")],
)
async def stop_suggestion_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Cancel an in-flight suggestion run."""
    from datetime import timezone as tz

    from app.models.feedback_eval import FeedbackSuggestionRun
    from app.routers.feedback_suggestion_worker import _suggestion_tasks

    run = await db.get(FeedbackSuggestionRun, run_id)
    if not run or run.project_id != project.id:
        raise HTTPException(status_code=404, detail="Suggestion run not found")
    if run.status not in ("pending", "running"):
        return _build_suggestion_run_response(run)

    task = _suggestion_tasks.pop(run_id, None)
    if task and not task.done():
        task.cancel()

    run.status = "cancelled"
    run.completed_at = datetime.now(tz.utc)
    await db.commit()
    await db.refresh(run)

    return _build_suggestion_run_response(run)


@router.post(
    "/suggestions/{feedback_id}/regenerate-expected-answer",
    response_model=RegenerateExpectedAnswerResponse,
    dependencies=[require_write("observe", "feedback")],
)
async def regenerate_expected_answer(
    feedback_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _user: User = Depends(get_current_user),
):
    """Re-run the LLM to draft criteria for an existing suggestion.

    Scoped to feedback the caller's project owns. Uses the same prompt as
    initial enrichment so reviewers can re-roll a draft they don't like.
    """
    from app.routers.dataset_helpers import (
        _extract_answer,
        _extract_user_prompt,
        build_contextualized_prompt,
        generate_expected_answer,
        load_trace_conversation_messages,
        summarize_conversation,
    )

    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    row_result = await db.execute(
        select(FeedbackScore, Trace)
        .join(Trace, FeedbackScore.trace_id == Trace.id)
        .where(
            FeedbackScore.id == feedback_id,
            FeedbackScore.integration_id.in_(project_integration_ids),
        )
    )
    row = row_result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Feedback not found")

    feedback, trace = row
    final_question = _extract_user_prompt(trace.input)
    if not final_question:
        raise HTTPException(status_code=422, detail="Trace input has no extractable user prompt")

    actual_answer = _extract_answer(trace.output)

    try:
        from app.services.analysis_llm import AnalysisLlmService

        llm_service = AnalysisLlmService(
            user_settings=_user.settings, project_settings=project.settings
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="LLM is not configured for this project") from exc

    # Match the suggestion-generation flow so re-rolled criteria see the same
    # context the original draft did. The summary captures topic only — never
    # the assistant's prior answers, which would leak the test's expected
    # output.
    trace_messages = await load_trace_conversation_messages(db, [trace.id])
    history = trace_messages.get(str(trace.id), [])
    older_turns = [t for t in history if t["content"].strip() != final_question.strip()]
    summary = await summarize_conversation(llm_service, older_turns) if older_turns else None
    prompt = build_contextualized_prompt(final_question, summary=summary)

    answer = await generate_expected_answer(
        llm_service,
        prompt,
        actual_answer,
        feedback.comment,
        db=db,
        project_id=project.id,
    )
    return RegenerateExpectedAnswerResponse(expected_answer=answer)
