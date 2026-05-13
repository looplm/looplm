"""Current-user permissions endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user
from app.config import settings
from app.db import get_db
from app.models.project import Project
from app.models.project_member import ALL_SECTIONS, ProjectMember
from app.models.user import User
from app.schemas.project_members import PermissionsResponse

router = APIRouter(prefix="/api/me", tags=["permissions"])


def _is_platform_admin(user: User) -> bool:
    if user.is_platform_admin:
        return True
    owner = settings.instance_owner_email
    return bool(owner) and user.email.lower() == owner.lower()


@router.get("/permissions", response_model=PermissionsResponse)
async def get_my_permissions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    project: Project = Depends(get_current_project),
):
    """Return the current user's role and allowed sections for the active project."""
    is_pa = _is_platform_admin(user)

    if project.owner_id == user.id:
        return PermissionsResponse(
            role="owner",
            allowed_sections=list(ALL_SECTIONS),
            allowed_pages=None,
            write_pages=None,
            is_platform_admin=is_pa,
        )

    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        return PermissionsResponse(
            role="member",
            allowed_sections=[],
            allowed_pages=[],
            write_pages=[],
            is_platform_admin=is_pa,
        )

    return PermissionsResponse(
        role=member.role,
        allowed_sections=member.allowed_sections or [],
        allowed_pages=member.allowed_pages,
        write_pages=member.write_pages,
        is_platform_admin=is_pa,
    )
