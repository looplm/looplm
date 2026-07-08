"""Feedback score endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from math import ceil
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section, require_write
from app.db import get_db
from app.models.models import FeedbackScore, Integration, IntegrationType, JsonImport, SyncStatus, Trace
from app.models.project import Project
from app.services.observe_filter import get_observe_trace_names
from app.schemas.feedback import (
    FeedbackListResponse,
    FeedbackScoreDetail,
    FeedbackScoreItem,
    PaginationInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"], dependencies=[require_section("observe", "feedback")])

# Include sub-routers
from app.routers.feedback_analytics import router as analytics_router
from app.routers.feedback_eval import router as eval_router
from app.routers.top_questions import router as top_questions_router
from app.routers.feedback_themes import router as feedback_themes_router
from app.routers.feedback_failure_modes import router as feedback_failure_modes_router

router.include_router(analytics_router)
router.include_router(eval_router)
router.include_router(top_questions_router)
router.include_router(feedback_themes_router)
router.include_router(feedback_failure_modes_router)


class FeedbackImportItem(BaseModel):
    score_name: str
    value: float
    external_trace_id: str = ""
    data_type: str = "BOOLEAN"
    comment: str | None = None
    scored_at: str | None = None


class FeedbackImportRequest(BaseModel):
    scores: list[FeedbackImportItem]
    filename: str = "import.json"


@router.post("/import", status_code=201, dependencies=[require_write("observe", "feedback")])
async def import_feedback(
    body: FeedbackImportRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Import feedback scores from a JSON file upload."""
    from app.encryption import encrypt_api_key

    if not body.scores:
        raise HTTPException(status_code=400, detail="No scores provided")

    # Find or create json_file integration
    result = await db.execute(
        select(Integration).where(
            Integration.project_id == project.id,
            Integration.type == IntegrationType.json_file,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        integration = Integration(
            project_id=project.id,
            type=IntegrationType.json_file,
            name="JSON Import",
            api_key=encrypt_api_key("json_file_placeholder"),
            sync_status=SyncStatus.idle,
        )
        db.add(integration)
        await db.flush()

    count = 0
    for item in body.scores:
        scored_at = datetime.fromisoformat(item.scored_at) if item.scored_at else datetime.utcnow()
        score = FeedbackScore(
            integration_id=integration.id,
            external_id=str(uuid4()),
            external_trace_id=item.external_trace_id or str(uuid4()),
            score_name=item.score_name,
            value=item.value,
            data_type=item.data_type,
            comment=item.comment,
            scored_at=scored_at,
        )
        db.add(score)
        count += 1

    # Record import history
    db.add(JsonImport(
        project_id=project.id,
        entity_type="feedback",
        filename=body.filename,
        record_count=count,
    ))

    await db.flush()
    return {"imported": count, "message": f"Imported {count} feedback scores"}


@router.get("", response_model=FeedbackListResponse)
async def list_feedback(
    score_name: str | None = None,
    exclude_score_name: str | None = None,
    value: float | None = None,
    verdict: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    integration_id: UUID | None = None,
    search: str | None = None,
    environment: str | None = None,
    include_user_ids: str | None = None,
    exclude_user_ids: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    from app.models.feedback_eval import FeedbackEvalResult

    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    # Subquery: latest eval result per feedback_id
    latest_eval = (
        select(
            FeedbackEvalResult.feedback_id,
            func.max(FeedbackEvalResult.created_at).label("latest_at"),
        )
        .group_by(FeedbackEvalResult.feedback_id)
        .subquery()
    )

    query = (
        select(FeedbackScore, Trace, FeedbackEvalResult)
        .outerjoin(Trace, FeedbackScore.trace_id == Trace.id)
        .outerjoin(latest_eval, latest_eval.c.feedback_id == FeedbackScore.id)
        .outerjoin(
            FeedbackEvalResult,
            and_(
                FeedbackEvalResult.feedback_id == FeedbackScore.id,
                FeedbackEvalResult.created_at == latest_eval.c.latest_at,
            ),
        )
        .where(FeedbackScore.integration_id.in_(project_integration_ids))
    )
    count_query = (
        select(func.count(FeedbackScore.id))
        .where(FeedbackScore.integration_id.in_(project_integration_ids))
    )

    if score_name:
        query = query.where(FeedbackScore.score_name == score_name)
        count_query = count_query.where(FeedbackScore.score_name == score_name)
    if exclude_score_name:
        query = query.where(FeedbackScore.score_name != exclude_score_name)
        count_query = count_query.where(FeedbackScore.score_name != exclude_score_name)
    if value is not None:
        query = query.where(FeedbackScore.value == value)
        count_query = count_query.where(FeedbackScore.value == value)
    if from_date:
        query = query.where(FeedbackScore.scored_at >= from_date)
        count_query = count_query.where(FeedbackScore.scored_at >= from_date)
    if to_date:
        query = query.where(FeedbackScore.scored_at <= to_date)
        count_query = count_query.where(FeedbackScore.scored_at <= to_date)
    if integration_id:
        query = query.where(FeedbackScore.integration_id == integration_id)
        count_query = count_query.where(FeedbackScore.integration_id == integration_id)
    observe_names = get_observe_trace_names(project)
    if environment:
        env_filter = Trace.trace_metadata["environment"].astext == environment
        query = query.where(env_filter)
        count_query = count_query.outerjoin(Trace, FeedbackScore.trace_id == Trace.id).where(env_filter)
    _count_has_trace_join = bool(environment)
    if observe_names:
        query = query.where(Trace.name.in_(observe_names))
        if not _count_has_trace_join:
            count_query = count_query.outerjoin(Trace, FeedbackScore.trace_id == Trace.id)
            _count_has_trace_join = True
        count_query = count_query.where(Trace.name.in_(observe_names))
    _inc_uids = [v.strip() for v in (include_user_ids or "").split(",") if v.strip()]
    _exc_uids = [v.strip() for v in (exclude_user_ids or "").split(",") if v.strip()]
    if _inc_uids:
        query = query.where(Trace.user_id.in_(_inc_uids))
        if not _count_has_trace_join:
            count_query = count_query.outerjoin(Trace, FeedbackScore.trace_id == Trace.id)
            _count_has_trace_join = True
        count_query = count_query.where(Trace.user_id.in_(_inc_uids))
    if _exc_uids:
        query = query.where(~Trace.user_id.in_(_exc_uids))
        if not _count_has_trace_join:
            count_query = count_query.outerjoin(Trace, FeedbackScore.trace_id == Trace.id)
            _count_has_trace_join = True
        count_query = count_query.where(~Trace.user_id.in_(_exc_uids))
    if search:
        from sqlalchemy import Text as SAText, cast as sa_cast

        search_filter = sa_cast(Trace.input, SAText).ilike(f"%{search}%")
        query = query.where(search_filter)
        if not _count_has_trace_join:
            count_query = count_query.outerjoin(Trace, FeedbackScore.trace_id == Trace.id)
            _count_has_trace_join = True
        count_query = count_query.where(search_filter)
    if verdict:
        if verdict == "none":
            query = query.where(FeedbackEvalResult.id.is_(None))
            count_query = (
                count_query
                .outerjoin(latest_eval, latest_eval.c.feedback_id == FeedbackScore.id)
                .outerjoin(
                    FeedbackEvalResult,
                    and_(
                        FeedbackEvalResult.feedback_id == FeedbackScore.id,
                        FeedbackEvalResult.created_at == latest_eval.c.latest_at,
                    ),
                )
                .where(FeedbackEvalResult.id.is_(None))
            )
        else:
            query = query.where(FeedbackEvalResult.verdict == verdict)
            count_query = (
                count_query
                .outerjoin(latest_eval, latest_eval.c.feedback_id == FeedbackScore.id)
                .outerjoin(
                    FeedbackEvalResult,
                    and_(
                        FeedbackEvalResult.feedback_id == FeedbackScore.id,
                        FeedbackEvalResult.created_at == latest_eval.c.latest_at,
                    ),
                )
                .where(FeedbackEvalResult.verdict == verdict)
            )

    total = (await db.execute(count_query)).scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = query.order_by(FeedbackScore.scored_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    rows = result.all()

    data = []
    for feedback, trace, eval_result in rows:
        item = FeedbackScoreItem(
            id=feedback.id,
            trace_id=feedback.trace_id,
            external_trace_id=feedback.external_trace_id,
            score_name=feedback.score_name,
            value=feedback.value,
            data_type=feedback.data_type,
            comment=feedback.comment,
            scored_at=feedback.scored_at,
            created_at=feedback.created_at,
            trace_input=trace.input if trace else None,
            trace_output=trace.output if trace else None,
            trace_status=trace.status.value if trace and trace.status else None,
            trace_start_time=trace.start_time if trace else None,
            trace_name=trace.name if trace else None,
            trace_metadata=trace.trace_metadata if trace else {},
            eval_verdict=eval_result.verdict if eval_result else None,
            eval_reasoning=eval_result.reasoning if eval_result else None,
            eval_confidence=eval_result.confidence if eval_result else None,
        )
        data.append(item)

    return FeedbackListResponse(
        data=data,
        pagination=PaginationInfo(page=page, per_page=per_page, total=total, total_pages=total_pages),
    )


@router.get("/{feedback_id}", response_model=FeedbackScoreDetail)
async def get_feedback(
    feedback_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    from app.models.feedback_eval import FeedbackEvalResult

    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    # Subquery: latest eval result for this feedback
    latest_eval = (
        select(func.max(FeedbackEvalResult.created_at).label("latest_at"))
        .where(FeedbackEvalResult.feedback_id == feedback_id)
        .scalar_subquery()
    )

    result = await db.execute(
        select(FeedbackScore, Trace, FeedbackEvalResult)
        .outerjoin(Trace, FeedbackScore.trace_id == Trace.id)
        .outerjoin(
            FeedbackEvalResult,
            and_(
                FeedbackEvalResult.feedback_id == FeedbackScore.id,
                FeedbackEvalResult.created_at == latest_eval,
            ),
        )
        .where(FeedbackScore.id == feedback_id, FeedbackScore.integration_id.in_(project_integration_ids))
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Feedback not found"}})

    feedback, trace, eval_result = row
    return FeedbackScoreDetail(
        id=feedback.id,
        trace_id=feedback.trace_id,
        external_trace_id=feedback.external_trace_id,
        score_name=feedback.score_name,
        value=feedback.value,
        data_type=feedback.data_type,
        comment=feedback.comment,
        scored_at=feedback.scored_at,
        created_at=feedback.created_at,
        trace_input=trace.input if trace else None,
        trace_output=trace.output if trace else None,
        trace_status=trace.status.value if trace and trace.status else None,
        trace_start_time=trace.start_time if trace else None,
        trace_name=trace.name if trace else None,
        trace_metadata=trace.trace_metadata if trace else {},
        trace_duration_ms=trace.duration_ms if trace else None,
        trace_error_message=trace.error_message if trace else None,
        eval_verdict=eval_result.verdict if eval_result else None,
        eval_reasoning=eval_result.reasoning if eval_result else None,
        eval_confidence=eval_result.confidence if eval_result else None,
    )
