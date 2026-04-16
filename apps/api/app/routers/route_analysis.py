"""Route frequency analysis endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section
from app.db import get_db
from app.models.project import Project
from app.schemas.route_analysis import BottleneckResponse, RouteAnalysisResponse
from app.services.route_analysis import get_bottlenecks, get_route_analysis

router = APIRouter(prefix="/api/route-analysis", tags=["route-analysis"], dependencies=[require_section("improve", "routes")])


@router.get("/{integration_id}", response_model=RouteAnalysisResponse)
async def route_analysis(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get route frequency analysis for an integration."""
    try:
        return await get_route_analysis(integration_id, project.id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{integration_id}/bottlenecks", response_model=BottleneckResponse)
async def route_bottlenecks(
    integration_id: UUID,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get top bottleneck nodes for an integration."""
    try:
        return await get_bottlenecks(integration_id, project.id, db, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
