"""Single-trace detail routes."""

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_project, require_section, require_write
from app.db import async_session, get_db
from app.models.models import Analysis, FeedbackScore, Integration, Trace
from app.models.project import Project
from app.schemas.traces import (
    AnalyzeResponse,
    TraceAnalysisResponse,
    TraceChildrenResponse,
    TraceDetail,
)
from app.services.analysis_service import analyze_trace

from .trace_helpers import _build_span_tree, _build_trace_tree

router = APIRouter(prefix="/api/traces", tags=["traces"], dependencies=[require_section("observe", "traces")])
logger = logging.getLogger(__name__)

_analysis_tasks: dict[UUID, asyncio.Task] = {}


async def _run_analysis_background(analysis_id: UUID, trace_id: UUID) -> None:
    """Run analysis in a background task with its own DB session."""
    try:
        async with async_session() as db:
            await analyze_trace(trace_id, db, analysis_id=analysis_id)
    except asyncio.CancelledError:
        logger.info("Background analysis task cancelled for analysis %s", analysis_id)
    except Exception as e:
        logger.error("Background analysis task failed for analysis %s: %s", analysis_id, e)


@router.get("/{trace_id}", response_model=TraceDetail)
async def get_trace(trace_id: UUID, db: AsyncSession = Depends(get_db), project: Project = Depends(get_current_project)):
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    result = await db.execute(
        select(Trace).where(Trace.id == trace_id, Trace.integration_id.in_(project_integration_ids)).options(selectinload(Trace.spans))
    )
    trace = result.scalar_one_or_none()
    if not trace:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Trace not found"}})

    # Count child runs (traces where root_trace_id == this trace)
    child_count_result = await db.execute(
        select(func.count(Trace.id)).where(Trace.root_trace_id == trace_id)
    )
    child_run_count = child_count_result.scalar() or 0

    detail = TraceDetail(
        id=trace.id,
        integration_id=trace.integration_id,
        external_id=trace.external_id,
        name=trace.name,
        thread_id=trace.thread_id,
        user_id=trace.user_id,
        parent_trace_id=trace.parent_trace_id,
        root_trace_id=trace.root_trace_id,
        run_type=trace.run_type,
        input=trace.input,
        output=trace.output,
        metadata=trace.trace_metadata or {},
        status=trace.status.value if trace.status else None,
        duration_ms=trace.duration_ms,
        start_time=trace.start_time,
        end_time=trace.end_time,
        error_message=trace.error_message,
        spans=_build_span_tree(trace.spans),
        child_run_count=child_run_count,
        created_at=trace.created_at,
    )
    return detail


@router.get("/{trace_id}/feedback")
async def get_trace_feedback(
    trace_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get all feedback scores for a trace."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    trace_check = await db.execute(
        select(Trace.id).where(Trace.id == trace_id, Trace.integration_id.in_(project_integration_ids))
    )
    if not trace_check.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Trace not found"}})

    result = await db.execute(
        select(FeedbackScore)
        .where(FeedbackScore.trace_id == trace_id)
        .order_by(FeedbackScore.scored_at.desc())
    )
    scores = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "score_name": s.score_name,
            "value": s.value,
            "comment": s.comment,
            "scored_at": s.scored_at.isoformat() if s.scored_at else None,
        }
        for s in scores
    ]


@router.get("/{trace_id}/children", response_model=TraceChildrenResponse)
async def get_trace_children(trace_id: UUID, db: AsyncSession = Depends(get_db), project: Project = Depends(get_current_project)):
    """Get all child runs for a trace as a hierarchical tree."""
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    # Verify the trace belongs to the project
    result = await db.execute(
        select(Trace).where(Trace.id == trace_id, Trace.integration_id.in_(project_integration_ids))
    )
    root_trace = result.scalar_one_or_none()
    if not root_trace:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Trace not found"}})

    # Fetch all children by root_trace_id
    children_result = await db.execute(
        select(Trace)
        .where(Trace.root_trace_id == trace_id)
        .order_by(Trace.start_time.asc())
    )
    children = list(children_result.scalars().all())

    tree = _build_trace_tree(children, trace_id)
    # Update root node with actual trace data
    tree.name = root_trace.name
    tree.run_type = root_trace.run_type
    tree.status = root_trace.status.value if root_trace.status else None
    tree.duration_ms = root_trace.duration_ms
    tree.start_time = root_trace.start_time
    tree.end_time = root_trace.end_time

    return TraceChildrenResponse(
        root=tree,
        children=tree.children,
        total_children=len(children),
    )


@router.get("/{trace_id}/analysis", response_model=TraceAnalysisResponse)
async def get_trace_analysis(trace_id: UUID, db: AsyncSession = Depends(get_db), project: Project = Depends(get_current_project)):
    # Verify trace belongs to project
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    trace_check = await db.execute(
        select(Trace.id).where(Trace.id == trace_id, Trace.integration_id.in_(project_integration_ids))
    )
    if not trace_check.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Trace not found"}})

    result = await db.execute(
        select(Analysis)
        .where(Analysis.trace_id == trace_id)
        .options(selectinload(Analysis.fix_suggestions))
        .order_by(Analysis.created_at.desc())
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Analysis not found for this trace"}})

    return TraceAnalysisResponse(analysis=analysis, fix_suggestions=analysis.fix_suggestions)


@router.post(
    "/{trace_id}/analyze",
    response_model=AnalyzeResponse,
    status_code=202,
    dependencies=[require_write("observe", "traces")],
)
async def trigger_analysis(trace_id: UUID, db: AsyncSession = Depends(get_db), project: Project = Depends(get_current_project)):
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    result = await db.execute(select(Trace).where(Trace.id == trace_id, Trace.integration_id.in_(project_integration_ids)))
    trace = result.scalar_one_or_none()
    if not trace:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Trace not found"}})

    # Create a placeholder analysis
    analysis = Analysis(trace_id=trace_id)
    db.add(analysis)
    await db.flush()
    await db.refresh(analysis)

    task = asyncio.create_task(_run_analysis_background(analysis.id, trace.id))
    _analysis_tasks[analysis.id] = task

    return AnalyzeResponse(trace_id=trace_id, analysis_id=analysis.id)
