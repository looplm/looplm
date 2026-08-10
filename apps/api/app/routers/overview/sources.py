"""GET /api/overview/sources — how many sources are indexed, and of what kind."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project
from app.db import get_db
from app.models.project import Project
from app.schemas.overview_sources import SourcesOverviewResponse
from app.services.overview_sources import DEFAULT_TOP, compute_sources_overview

router = APIRouter()


@router.get("/sources", response_model=SourcesOverviewResponse)
async def overview_sources(
    provider_id: Optional[UUID] = None,
    top: int = Query(DEFAULT_TOP, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Registry counts by business metadata, coverage status, and provider type.

    Not filtered by the page's date range: this is the current state of the index, not a
    period. The live file/content-type breakdown comes from
    ``/api/index-explorer/file-types``, fetched separately so a slow or broken index
    cannot hold up this response.
    """
    return await compute_sources_overview(db, project, provider_id=provider_id, top=top)
