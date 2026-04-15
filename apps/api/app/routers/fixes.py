"""Fix suggestion endpoints."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project
from app.db import get_db
from app.models.models import Analysis, FixStatus, FixSuggestion, Integration, Trace
from app.models.project import Project
from app.schemas.fixes import FixApplyResponse

router = APIRouter(prefix="/api/fixes", tags=["fixes"])


@router.post("/{fix_id}/apply", response_model=FixApplyResponse)
async def apply_fix(fix_id: UUID, db: AsyncSession = Depends(get_db), project: Project = Depends(get_current_project)):
    # Scope fix to project's data: FixSuggestion -> Analysis -> Trace -> Integration(project_id)
    project_integration_ids = select(Integration.id).where(Integration.project_id == project.id)
    project_trace_ids = select(Trace.id).where(Trace.integration_id.in_(project_integration_ids))
    user_analysis_ids = select(Analysis.id).where(Analysis.trace_id.in_(project_trace_ids))
    result = await db.execute(
        select(FixSuggestion).where(FixSuggestion.id == fix_id, FixSuggestion.analysis_id.in_(user_analysis_ids))
    )
    fix = result.scalar_one_or_none()
    if not fix:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Fix not found"}})
    if fix.status != FixStatus.pending:
        raise HTTPException(status_code=409, detail={"error": {"code": "CONFLICT", "message": "Fix already applied or dismissed"}})

    fix.status = FixStatus.applied
    now = datetime.now(timezone.utc)
    await db.flush()

    return FixApplyResponse(id=fix.id, status="applied", applied_at=now)
