"""Authentication utilities: JWT tokens, password hashing, dependency."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

bearer_scheme = HTTPBearer()


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: UUID, expires_delta: timedelta | None = None) -> str:
    issued_at = datetime.now(timezone.utc)
    expire = issued_at + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": str(user_id), "exp": expire, "iat": issued_at, "jti": str(uuid4()), "type": "access"}
    return jwt.encode(payload, settings.api_secret_key, algorithm=ALGORITHM)


def create_refresh_token(user_id: UUID) -> str:
    issued_at = datetime.now(timezone.utc)
    expire = issued_at + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire, "iat": issued_at, "jti": str(uuid4()), "type": "refresh"}
    return jwt.encode(payload, settings.api_secret_key, algorithm=ALGORITHM)


def verify_refresh_token(token: str) -> UUID:
    """Decode and validate a refresh token. Returns the user ID from the sub claim."""
    try:
        payload = jwt.decode(token, settings.api_secret_key, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
        return UUID(user_id)
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency that extracts and validates JWT, returns the User."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.api_secret_key, algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


async def get_current_project(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_project_id: str | None = Header(None),
) -> Project:
    """Dependency that resolves the active project from X-Project-Id header.

    Access is granted if the user owns the project OR is a member.
    """
    if x_project_id:
        try:
            project_uuid = UUID(x_project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project ID format")

        # Check ownership first
        result = await db.execute(
            select(Project).where(Project.id == project_uuid, Project.owner_id == _user.id)
        )
        project = result.scalar_one_or_none()
        if not project:
            # Check membership
            result = await db.execute(
                select(Project)
                .join(ProjectMember, ProjectMember.project_id == Project.id)
                .where(Project.id == project_uuid, ProjectMember.user_id == _user.id)
            )
            project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    # No header: fall back to first project the user owns or is a member of
    owned = select(Project).where(Project.owner_id == _user.id)
    member_of = (
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == _user.id)
    )
    result = await db.execute(
        owned.union(member_of).order_by(Project.created_at.asc()).limit(1)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=400, detail="No projects found. Create a project first.")
    return project


def require_section(section: str):
    """Factory that returns a FastAPI dependency enforcing section access.

    Project owners bypass the check (full access). Members must have the
    section listed in their ``allowed_sections``.
    """

    async def _check_section(
        user: User = Depends(get_current_user),
        project: Project = Depends(get_current_project),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        # Owner always has full access
        if project.owner_id == user.id:
            return
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user.id,
            )
        )
        member = result.scalar_one_or_none()
        if not member or section not in (member.allowed_sections or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have access to the {section} section",
            )

    return Depends(_check_section)


async def require_project_admin(
    user: User = Depends(get_current_user),
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Dependency that ensures the current user is the project owner or an admin member."""
    if project.owner_id == user.id:
        return
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        )
    )
    member = result.scalar_one_or_none()
    if not member or member.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
