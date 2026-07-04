"""Retrieval-readiness endpoint — config-status banner for the Retrieval/Labeling pages.

Section-gated at ``evaluate`` (no page) so both the pipeline and labeling pages can read it, and
project-scoped via the ``X-Project-Id`` header (``get_current_project``), so any project member —
not just the owner — sees the banner. Read-only; the live embed probe behind it is cached.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section
from app.db import get_db
from app.models.project import Project
from app.schemas.retrieval import RetrievalReadiness
from app.services.retrieval_readiness import compute_retrieval_readiness

router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline"],
    dependencies=[require_section("evaluate")],
)


@router.get("/retrieval-readiness", response_model=RetrievalReadiness)
async def retrieval_readiness(
    refresh: bool = Query(False, description="Bypass the cached embedding probe and re-check live."),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
) -> RetrievalReadiness:
    """Is the project configured to measure retrieval quality (embedding model + index semantic)?"""
    return await compute_retrieval_readiness(db, project, refresh=refresh)
