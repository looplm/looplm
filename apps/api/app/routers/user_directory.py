"""User directory endpoints — name raw user ids, and group them.

Two resources, both project-scoped:

* ``/api/user-identities`` — a name plus the raw ``Trace.user_id`` values belonging to it.
* ``/api/user-groups`` — a filterable set of identities and/or raw user ids.

Membership lists are JSONB arrays (see ``app/models/user_directory.py``), so the invariants
that a relational schema would enforce live here: a raw user id belongs to at most one identity
per project, group members must exist, and deleting an identity prunes it out of every group.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section, require_write
from app.db import get_db
from app.models.project import Project
from app.models.user_directory import UserGroup, UserIdentity
from app.schemas.user_directory import (
    UserGroupCreate,
    UserGroupListResponse,
    UserGroupResponse,
    UserGroupUpdate,
    UserIdentityCreate,
    UserIdentityListResponse,
    UserIdentityResponse,
    UserIdentityUpdate,
)

# The directory is edited from Settings but it scopes the Observe views, so it reuses the
# observe/traces permission pair rather than introducing a new page in SECTION_PAGES.
_SECTION = ("observe", "traces")

identities_router = APIRouter(
    prefix="/api/user-identities",
    tags=["user-directory"],
    dependencies=[require_section(*_SECTION)],
)
groups_router = APIRouter(
    prefix="/api/user-groups",
    tags=["user-directory"],
    dependencies=[require_section(*_SECTION)],
)


def _not_found(what: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error": {"code": "NOT_FOUND", "message": f"{what} not found"}},
    )


def _duplicate(message: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"error": {"code": "DUPLICATE", "message": message}},
    )


def _clean_ids(values: list[str] | None) -> list[str]:
    """Strip blanks and duplicates while preserving the caller's order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in values or []:
        value = raw.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


async def _load_identities(db: AsyncSession, project: Project) -> list[UserIdentity]:
    result = await db.execute(
        select(UserIdentity)
        .where(UserIdentity.project_id == project.id)
        .order_by(UserIdentity.name)
    )
    return list(result.scalars().all())


async def _load_groups(db: AsyncSession, project: Project) -> list[UserGroup]:
    result = await db.execute(
        select(UserGroup).where(UserGroup.project_id == project.id).order_by(UserGroup.name)
    )
    return list(result.scalars().all())


async def _assert_name_free(
    db: AsyncSession,
    project: Project,
    model: type[UserIdentity] | type[UserGroup],
    name: str,
    *,
    exclude_id: UUID | None = None,
) -> None:
    query = select(model).where(model.project_id == project.id, model.name == name)
    if exclude_id is not None:
        query = query.where(model.id != exclude_id)
    if (await db.execute(query)).scalars().first() is not None:
        label = "identity" if model is UserIdentity else "group"
        raise _duplicate(f"A user {label} named '{name}' already exists")


async def _assert_ids_unclaimed(
    db: AsyncSession,
    project: Project,
    user_ids: list[str],
    *,
    exclude_id: UUID | None = None,
) -> None:
    """A raw user id may belong to at most one identity per project."""
    if not user_ids:
        return
    wanted = set(user_ids)
    for identity in await _load_identities(db, project):
        if identity.id == exclude_id:
            continue
        clash = wanted.intersection(identity.user_ids or [])
        if clash:
            raise _duplicate(
                f"User id '{sorted(clash)[0]}' is already mapped to '{identity.name}'"
            )


async def _clean_identity_ids(
    db: AsyncSession, project: Project, identity_ids: list[UUID] | None
) -> list[str]:
    """Keep only identities that exist in this project, deduped, order preserved."""
    if not identity_ids:
        return []
    known = {str(i.id) for i in await _load_identities(db, project)}
    seen: set[str] = set()
    out: list[str] = []
    for identity_id in identity_ids:
        value = str(identity_id)
        if value in seen:
            continue
        if value not in known:
            raise _not_found(f"User identity '{value}'")
        seen.add(value)
        out.append(value)
    return out


@identities_router.get("", response_model=UserIdentityListResponse)
async def list_user_identities(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List every named identity in the project."""
    identities = await _load_identities(db, project)
    return UserIdentityListResponse(data=identities, total=len(identities))


@identities_router.post(
    "",
    response_model=UserIdentityResponse,
    status_code=201,
    dependencies=[require_write(*_SECTION)],
)
async def create_user_identity(
    body: UserIdentityCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Name a person and attach their raw user ids."""
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "INVALID_NAME", "message": "Name must not be empty"}},
        )
    user_ids = _clean_ids(body.user_ids)
    await _assert_name_free(db, project, UserIdentity, name)
    await _assert_ids_unclaimed(db, project, user_ids)

    identity = UserIdentity(project_id=project.id, name=name, user_ids=user_ids)
    db.add(identity)
    await db.flush()
    await db.refresh(identity)
    return identity


@identities_router.patch(
    "/{identity_id}",
    response_model=UserIdentityResponse,
    dependencies=[require_write(*_SECTION)],
)
async def update_user_identity(
    identity_id: UUID,
    body: UserIdentityUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Rename an identity and/or replace the set of user ids it owns."""
    result = await db.execute(
        select(UserIdentity).where(
            UserIdentity.id == identity_id, UserIdentity.project_id == project.id
        )
    )
    identity = result.scalar_one_or_none()
    if not identity:
        raise _not_found("User identity")

    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "INVALID_NAME", "message": "Name must not be empty"}},
            )
        await _assert_name_free(db, project, UserIdentity, name, exclude_id=identity.id)
        identity.name = name
    if "user_ids" in data:
        user_ids = _clean_ids(data["user_ids"])
        await _assert_ids_unclaimed(db, project, user_ids, exclude_id=identity.id)
        identity.user_ids = user_ids

    identity.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(identity)
    return identity


@identities_router.delete(
    "/{identity_id}", status_code=204, dependencies=[require_write(*_SECTION)]
)
async def delete_user_identity(
    identity_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Delete an identity and drop it from every group that referenced it."""
    result = await db.execute(
        select(UserIdentity).where(
            UserIdentity.id == identity_id, UserIdentity.project_id == project.id
        )
    )
    identity = result.scalar_one_or_none()
    if not identity:
        raise _not_found("User identity")

    stale = str(identity.id)
    for group in await _load_groups(db, project):
        members = list(group.identity_ids or [])
        if stale in members:
            # Reassign rather than mutate: a plain JSONB list is not change-tracked.
            group.identity_ids = [m for m in members if m != stale]
            group.updated_at = datetime.now(timezone.utc)

    await db.delete(identity)
    return None


@groups_router.get("", response_model=UserGroupListResponse)
async def list_user_groups(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List every user group in the project."""
    groups = await _load_groups(db, project)
    return UserGroupListResponse(data=groups, total=len(groups))


@groups_router.post(
    "",
    response_model=UserGroupResponse,
    status_code=201,
    dependencies=[require_write(*_SECTION)],
)
async def create_user_group(
    body: UserGroupCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Create a group of identities and/or raw user ids."""
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "INVALID_NAME", "message": "Name must not be empty"}},
        )
    await _assert_name_free(db, project, UserGroup, name)

    group = UserGroup(
        project_id=project.id,
        name=name,
        description=body.description,
        identity_ids=await _clean_identity_ids(db, project, body.identity_ids),
        user_ids=_clean_ids(body.user_ids),
    )
    db.add(group)
    await db.flush()
    await db.refresh(group)
    return group


@groups_router.patch(
    "/{group_id}",
    response_model=UserGroupResponse,
    dependencies=[require_write(*_SECTION)],
)
async def update_user_group(
    group_id: UUID,
    body: UserGroupUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Rename a group, edit its description, or replace its membership."""
    result = await db.execute(
        select(UserGroup).where(UserGroup.id == group_id, UserGroup.project_id == project.id)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise _not_found("User group")

    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "INVALID_NAME", "message": "Name must not be empty"}},
            )
        await _assert_name_free(db, project, UserGroup, name, exclude_id=group.id)
        group.name = name
    if "description" in data:
        group.description = data["description"]
    if "identity_ids" in data:
        group.identity_ids = await _clean_identity_ids(db, project, data["identity_ids"])
    if "user_ids" in data:
        group.user_ids = _clean_ids(data["user_ids"])

    group.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(group)
    return group


@groups_router.delete("/{group_id}", status_code=204, dependencies=[require_write(*_SECTION)])
async def delete_user_group(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Delete a group. Identities and their user ids are untouched."""
    result = await db.execute(
        select(UserGroup).where(UserGroup.id == group_id, UserGroup.project_id == project.id)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise _not_found("User group")
    await db.delete(group)
    return None
