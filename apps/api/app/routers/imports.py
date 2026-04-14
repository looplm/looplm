"""Import history endpoints."""

from __future__ import annotations

from math import ceil

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project
from app.db import get_db
from app.models.models import JsonImport
from app.models.project import Project
from app.schemas.evaluations import PaginationInfo

router = APIRouter(prefix="/api/imports", tags=["imports"])


class JsonImportItem(BaseModel):
    id: str
    entity_type: str
    filename: str
    record_count: int
    status: str
    error_message: str | None
    created_at: str

    class Config:
        from_attributes = True


class JsonImportListResponse(BaseModel):
    data: list[JsonImportItem]
    pagination: PaginationInfo


@router.get("", response_model=JsonImportListResponse)
async def list_imports(
    entity_type: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List import history, optionally filtered by entity type."""
    base = [JsonImport.project_id == project.id]
    if entity_type:
        base.append(JsonImport.entity_type == entity_type)

    total = (await db.execute(
        select(func.count(JsonImport.id)).where(*base)
    )).scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = (
        select(JsonImport)
        .where(*base)
        .order_by(JsonImport.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(query)
    imports = result.scalars().all()

    data = [
        JsonImportItem(
            id=str(i.id),
            entity_type=i.entity_type,
            filename=i.filename,
            record_count=i.record_count,
            status=i.status.value if hasattr(i.status, "value") else i.status,
            error_message=i.error_message,
            created_at=i.created_at.isoformat(),
        )
        for i in imports
    ]

    return JsonImportListResponse(
        data=data,
        pagination=PaginationInfo(page=page, per_page=per_page, total=total, total_pages=total_pages),
    )
