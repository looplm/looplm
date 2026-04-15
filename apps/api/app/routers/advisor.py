"""Architecture advisor endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section
from app.db import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.advisor import AdvisorAnalyzeRequest, AdvisorResponse
from app.services.architecture_advisor import analyze_architecture, get_latest_suggestions

router = APIRouter(prefix="/api/advisor", tags=["advisor"], dependencies=[require_section("improve")])


@router.post("/{integration_id}/analyze", response_model=AdvisorResponse)
async def trigger_analysis(
    integration_id: UUID,
    body: AdvisorAnalyzeRequest | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Trigger LLM-based architecture analysis."""
    try:
        return await analyze_architecture(
            integration_id, project.id, db,
            extra_context=body.extra_context if body else "",
            user_settings=user.settings,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")


@router.get("/{integration_id}/suggestions", response_model=AdvisorResponse)
async def get_suggestions(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    _project: Project = Depends(get_current_project),
):
    """Get latest persisted architecture suggestions."""
    result = await get_latest_suggestions(integration_id, db)
    if not result:
        raise HTTPException(status_code=404, detail="No suggestions found. Run POST /analyze first.")
    return result
