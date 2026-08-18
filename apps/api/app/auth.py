"""Authentication utilities: JWT tokens, password hashing, dependency."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import bcrypt
from jose import JWTError, jwt
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.integrations import IngestKey, Integration
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 2

INGEST_KEY_PREFIX = "llm_sk_"

bearer_scheme = HTTPBearer()
# Separate scheme for machine clients (SDKs) pushing traces. auto_error returns
# 401 on a missing/garbled Authorization header before our handler runs.
ingest_bearer_scheme = HTTPBearer(auto_error=True)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: UUID, expires_delta: timedelta | None = None) -> str:
    issued_at = datetime.now(timezone.utc)
    expire = issued_at + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": str(user_id), "exp": expire, "iat": issued_at, "jti": str(uuid4()), "type": "access"}
    return jwt.encode(payload, settings.api_secret_key, algorithm=ALGORITHM)


def create_refresh_token(
    user_id: UUID, *, jti: UUID | None = None, family_id: UUID | None = None
) -> tuple[str, UUID, UUID, datetime]:
    """Mint a refresh token.

    Returns ``(token, jti, family_id, expires_at)`` so the caller can persist the matching
    `RefreshSession` row - a refresh token is only accepted while its row is live.
    """
    issued_at = datetime.now(timezone.utc)
    expire = issued_at + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    token_jti = jti or uuid4()
    token_family = family_id or token_jti
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": issued_at,
        "jti": str(token_jti),
        "fam": str(token_family),
        "type": "refresh",
    }
    return (
        jwt.encode(payload, settings.api_secret_key, algorithm=ALGORITHM),
        token_jti,
        token_family,
        expire,
    )


def decode_refresh_token(token: str) -> tuple[UUID, UUID, UUID | None]:
    """Decode and validate a refresh token's signature and claims.

    Returns ``(user_id, jti, family_id)``. Says nothing about whether the token has been
    revoked - that is a database question, see `services.auth_sessions.rotate`.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
    )
    try:
        payload = jwt.decode(token, settings.api_secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise invalid
    if payload.get("type") != "refresh":
        raise invalid
    try:
        user_id = UUID(str(payload.get("sub")))
        jti = UUID(str(payload.get("jti")))
    except (TypeError, ValueError):
        raise invalid
    fam_raw = payload.get("fam")
    try:
        family_id = UUID(str(fam_raw)) if fam_raw else None
    except (TypeError, ValueError):
        family_id = None
    return user_id, jti, family_id


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency that extracts and validates an access JWT, returns the User.

    The ``type`` claim is mandatory. Every token this app signs uses the same key and algorithm
    (refresh tokens, the GitHub OAuth state, verification links), so without the claim check
    any of them authenticates every endpoint.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, settings.api_secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise invalid
    if payload.get("type") != "access":
        raise invalid
    try:
        user_uuid = UUID(str(payload.get("sub")))
    except (TypeError, ValueError):
        raise invalid

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def _load_project_for_user(
    db: AsyncSession, user: User, project_id: UUID
) -> Project | None:
    """The project, if *user* owns it or is a member of it. None otherwise."""
    # Ownership first - owners have no ProjectMember row.
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is not None:
        return project
    result = await db.execute(
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(Project.id == project_id, ProjectMember.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def get_path_project(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Resolve the project named in the URL path and assert the caller belongs to it.

    X-Project-Id is ignored on purpose. Authorizing against the header while querying by the
    path parameter is how cross-tenant access happens, so any router mounted under
    ``/api/projects/{project_id}/...`` must authorize against the path - the path *is* the
    resource identity.
    """
    project = await _load_project_for_user(db, user, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def get_current_project(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_project_id: str | None = Header(None),
) -> Project:
    """Dependency that resolves the active project from X-Project-Id header.

    Access is granted if the user owns the project OR is a member. Do not use this on a route
    that also takes a ``project_id`` path parameter - see `get_path_project`.
    """
    if x_project_id:
        try:
            project_uuid = UUID(x_project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project ID format")

        project = await _load_project_for_user(db, _user, project_uuid)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    # No header: fall back to first project the user owns or is a member of.
    # Use a single ORM-friendly query (union() drops to Core rows, so
    # scalar_one_or_none() would yield the first column — Project.id — instead
    # of a Project entity).
    member_subquery = select(ProjectMember.project_id).where(
        ProjectMember.user_id == _user.id
    )
    result = await db.execute(
        select(Project)
        .where(
            or_(
                Project.owner_id == _user.id,
                Project.id.in_(member_subquery),
            )
        )
        .order_by(Project.created_at.asc())
        .limit(1)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=400, detail="No projects found. Create a project first.")
    return project


# ── Ingest keys (machine auth for the first-party tracing SDK) ──────────

def hash_ingest_key(token: str) -> str:
    """Return the sha256 hex digest used to look up / store an ingest key."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_ingest_key() -> tuple[str, str, str]:
    """Mint a new ingest key.

    Returns ``(plaintext, key_hash, key_prefix)``. The plaintext is shown to the
    user exactly once; only the hash and a short display prefix are persisted.
    """
    plaintext = INGEST_KEY_PREFIX + secrets.token_urlsafe(32)
    return plaintext, hash_ingest_key(plaintext), plaintext[: len(INGEST_KEY_PREFIX) + 4]


async def get_ingest_context(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(ingest_bearer_scheme)],
    db: AsyncSession = Depends(get_db),
) -> tuple[Integration, Project]:
    """Resolve (Integration, Project) from an ingest key — no user/JWT involved.

    Used by the push-based ingest endpoint. 401 on missing/invalid/revoked key.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked ingest key"
    )
    token = credentials.credentials
    if not token.startswith(INGEST_KEY_PREFIX):
        raise unauthorized

    result = await db.execute(
        select(IngestKey).where(
            IngestKey.key_hash == hash_ingest_key(token),
            IngestKey.revoked_at.is_(None),
        )
    )
    key = result.scalar_one_or_none()
    if key is None:
        raise unauthorized

    result = await db.execute(select(Integration).where(Integration.id == key.integration_id))
    integration = result.scalar_one_or_none()
    if integration is None:
        raise unauthorized

    result = await db.execute(select(Project).where(Project.id == integration.project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise unauthorized

    # Throttled liveness: avoid writing on every request under high throughput.
    now = datetime.now(timezone.utc)
    last_used = key.last_used_at
    if last_used is not None and last_used.tzinfo is None:
        last_used = last_used.replace(tzinfo=timezone.utc)
    if last_used is None or (now - last_used).total_seconds() > 60:
        key.last_used_at = now
        await db.flush()

    return integration, project


async def _load_member(
    user: User, project: Project, db: AsyncSession
) -> ProjectMember | None:
    """Load the ProjectMember row for (user, project) or None."""
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        )
    )
    return result.scalar_one_or_none()


def _assert_read_access(
    member: ProjectMember | None, section: str, page: str | None
) -> None:
    """Raise 403 if member cannot read the given section/page."""
    if not member or section not in (member.allowed_sections or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You do not have access to the {section} section",
        )
    if page is not None and member.allowed_pages is not None:
        if page not in member.allowed_pages:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have access to the {page} page",
            )


def require_section(section: str, page: str | None = None):
    """Factory that returns a FastAPI dependency enforcing section and page read access.

    Project owners bypass the check (full access). Members must have the
    section listed in their ``allowed_sections``. When *page* is given and
    the member has an explicit ``allowed_pages`` list, the page must appear
    in that list as well.
    """

    async def _check_section(
        user: User = Depends(get_current_user),
        project: Project = Depends(get_current_project),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        if project.owner_id == user.id:
            return
        member = await _load_member(user, project, db)
        _assert_read_access(member, section, page)

    return Depends(_check_section)


def require_write(section: str, page: str):
    """Factory that returns a FastAPI dependency enforcing write access on a page.

    Project owners and admin members always pass. For regular members,
    ``write_pages`` null means legacy full-write on all allowed pages; a
    list restricts writes to the listed pages. Read access (section + page)
    is also checked — you cannot write what you cannot read.
    """

    async def _check_write(
        user: User = Depends(get_current_user),
        project: Project = Depends(get_current_project),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        if project.owner_id == user.id:
            return
        member = await _load_member(user, project, db)
        _assert_read_access(member, section, page)
        assert member is not None  # guaranteed by _assert_read_access
        if member.role == "admin":
            return
        # Fail closed. NULL used to mean "legacy full write", which silently upgraded every
        # invited member to read-write (the invitation path never copied write_pages).
        if member.write_pages is None or page not in member.write_pages:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Read-only access to the {page} page; write permission required",
            )

    return Depends(_check_write)


async def _assert_project_admin(user: User, project: Project, db: AsyncSession) -> None:
    """Raise 403 unless *user* owns *project* or is an admin member of it."""
    if project.owner_id == user.id:
        return
    member = await _load_member(user, project, db)
    if not member or member.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


async def require_project_admin(
    user: User = Depends(get_current_user),
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Dependency that ensures the current user is the project owner or an admin member."""
    await _assert_project_admin(user, project, db)


async def require_path_project_admin(
    user: User = Depends(get_current_user),
    project: Project = Depends(get_path_project),
    db: AsyncSession = Depends(get_db),
) -> None:
    """`require_project_admin` for routers mounted under ``/api/projects/{project_id}/...``.

    Resolves the project from the path, so the header cannot be used to authorize against one
    project while the handler reads or writes another.
    """
    await _assert_project_admin(user, project, db)


def _is_instance_owner_email(email: str) -> bool:
    owner = settings.instance_owner_email
    return bool(owner) and email.lower() == owner.lower()


async def require_platform_admin(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency that ensures the current user is a platform admin.

    A user is a platform admin if `is_platform_admin` is true, or if their
    email matches `INSTANCE_OWNER_EMAIL`. The env match auto-promotes the user
    row so subsequent checks are local.
    """
    if user.is_platform_admin:
        return user

    if _is_instance_owner_email(user.email):
        user.is_platform_admin = True
        await db.flush()
        return user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Platform admin access required",
    )
