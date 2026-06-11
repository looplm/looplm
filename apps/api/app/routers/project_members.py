"""Project member management endpoints — invite, update, remove members and invitations."""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_project_admin
from app.config import settings as app_settings
from app.db import get_db
from app.models.project import Project
from app.models.project_invitation import ProjectInvitation
from app.models.project_member import ALL_PAGES, ALL_SECTIONS, PAGE_TO_SECTION, ProjectMember
from app.models.user import User
from app.schemas.project_members import (
    InviteResponse,
    MemberInvite,
    MemberListResponse,
    MemberResponse,
    MemberUpdate,
)
from app.services.email_service import send_invitation_email

router = APIRouter(prefix="/api/projects/{project_id}/members", tags=["members"])


def _validate_pages(
    allowed_pages: list[str] | None, allowed_sections: list[str]
) -> None:
    """Validate that pages are known and belong to allowed sections."""
    if allowed_pages is None:
        return
    invalid = set(allowed_pages) - set(ALL_PAGES)
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid pages: {', '.join(sorted(invalid))}")
    for page in allowed_pages:
        if PAGE_TO_SECTION[page] not in allowed_sections:
            raise HTTPException(
                status_code=400,
                detail=f"Page '{page}' belongs to section '{PAGE_TO_SECTION[page]}' "
                f"which is not in allowed sections",
            )


def _validate_write_pages(
    write_pages: list[str] | None, allowed_pages: list[str] | None
) -> None:
    """Ensure write_pages is a subset of allowed_pages (when both non-null)."""
    if write_pages is None or allowed_pages is None:
        return
    orphans = set(write_pages) - set(allowed_pages)
    if orphans:
        raise HTTPException(
            status_code=400,
            detail=f"write_pages must be a subset of allowed_pages; "
            f"unknown entries: {', '.join(sorted(orphans))}",
        )


def _member_response(member: ProjectMember, email: str) -> MemberResponse:
    return MemberResponse(
        id=member.id,
        user_id=member.user_id,
        email=email,
        role=member.role,
        allowed_sections=member.allowed_sections or [],
        allowed_pages=member.allowed_pages,
        write_pages=member.write_pages,
        status="active",
        created_at=member.created_at,
    )


def _invitation_response(inv: ProjectInvitation) -> MemberResponse:
    return MemberResponse(
        id=inv.id,
        user_id=None,
        email=inv.email,
        role=inv.role,
        allowed_sections=inv.allowed_sections or [],
        allowed_pages=inv.allowed_pages,
        write_pages=inv.write_pages,
        status="pending",
        created_at=inv.created_at,
    )


def _owner_response(project: Project, email: str) -> MemberResponse:
    """Synthetic, read-only member row for the project owner.

    The owner lives on ``Project.owner_id`` (not in project_members), so this row
    is built on the fly. ``id`` is the owner's user id — there is no member row to
    target — and the ``owner`` role signals to the UI that it can't be edited or
    removed, only transferred.
    """
    return MemberResponse(
        id=project.owner_id,
        user_id=project.owner_id,
        email=email,
        role="owner",
        allowed_sections=list(ALL_SECTIONS),
        allowed_pages=None,
        write_pages=None,
        status="active",
        created_at=project.created_at,
    )


def _build_invite_url(token: str, email: str) -> str:
    return f"{app_settings.frontend_url}/register?invite={token}&email={quote(email)}"


@router.get("", response_model=MemberListResponse)
async def list_members(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    _project: Project = Depends(get_current_project),
    _admin: None = Depends(require_project_admin),
):
    # Owner row first (lives on Project.owner_id, not in project_members).
    owner_email = (
        await db.execute(select(User.email).where(User.id == _project.owner_id))
    ).scalar_one()
    members = [_owner_response(_project, owner_email)]

    # Active members
    result = await db.execute(
        select(ProjectMember, User.email)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.created_at.asc())
    )
    members += [_member_response(m, email) for m, email in result.all()]

    # Pending invitations
    result = await db.execute(
        select(ProjectInvitation)
        .where(ProjectInvitation.project_id == project_id)
        .order_by(ProjectInvitation.created_at.asc())
    )
    for inv in result.scalars().all():
        members.append(_invitation_response(inv))

    return MemberListResponse(data=members)


@router.post("", response_model=InviteResponse, status_code=201)
async def invite_member(
    project_id: UUID,
    body: MemberInvite,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    _project: Project = Depends(get_current_project),
    _admin: None = Depends(require_project_admin),
):
    # Validate sections
    invalid = set(body.allowed_sections) - set(ALL_SECTIONS)
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid sections: {', '.join(invalid)}")
    _validate_pages(body.allowed_pages, body.allowed_sections)
    _validate_write_pages(body.write_pages, body.allowed_pages)

    # New invites default to read-only (empty write_pages) when caller omits the field.
    # Admin role bypasses write checks regardless, so this is harmless for admins.
    write_pages = body.write_pages if body.write_pages is not None else []

    # Check if user already exists
    result = await db.execute(select(User).where(User.email == body.email))
    target_user = result.scalar_one_or_none()

    if target_user:
        # User exists — create membership directly
        if target_user.id == _project.owner_id:
            raise HTTPException(status_code=400, detail="Cannot add the project owner as a member")

        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == target_user.id,
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="User is already a member of this project")

        member = ProjectMember(
            project_id=project_id,
            user_id=target_user.id,
            role=body.role,
            allowed_sections=body.allowed_sections,
            allowed_pages=body.allowed_pages,
            write_pages=write_pages,
        )
        db.add(member)
        await db.flush()
        await db.refresh(member)
        return InviteResponse(
            id=member.id,
            email=body.email,
            role=member.role,
            allowed_sections=member.allowed_sections or [],
            allowed_pages=member.allowed_pages,
            write_pages=member.write_pages,
            status="active",
        )

    # User does not exist — create a pending invitation
    # Check for existing pending invitation
    result = await db.execute(
        select(ProjectInvitation).where(
            ProjectInvitation.project_id == project_id,
            ProjectInvitation.email == body.email,
        )
    )
    existing_inv = result.scalar_one_or_none()
    if existing_inv:
        raise HTTPException(
            status_code=409,
            detail="An invitation for this email is already pending",
        )

    invitation = ProjectInvitation(
        project_id=project_id,
        invited_by=_user.id,
        email=body.email,
        role=body.role,
        allowed_sections=body.allowed_sections,
        allowed_pages=body.allowed_pages,
        write_pages=write_pages,
    )
    db.add(invitation)
    await db.flush()
    await db.refresh(invitation)

    invite_url = _build_invite_url(invitation.token, body.email)
    email_sent = send_invitation_email(
        to=body.email,
        inviter_email=_user.email,
        project_name=_project.name,
        invite_url=invite_url,
    )

    return InviteResponse(
        id=invitation.id,
        email=body.email,
        role=invitation.role,
        allowed_sections=invitation.allowed_sections or [],
        allowed_pages=invitation.allowed_pages,
        write_pages=invitation.write_pages,
        status="pending",
        invite_link=invite_url,
        email_sent=email_sent,
    )


def _apply_update(
    target: ProjectMember | ProjectInvitation, body: MemberUpdate
) -> None:
    """Apply PATCH body fields to a member or invitation, with cascading cleanup."""
    if body.role is not None:
        target.role = body.role
    if body.allowed_sections is not None:
        invalid = set(body.allowed_sections) - set(ALL_SECTIONS)
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid sections: {', '.join(invalid)}")
        target.allowed_sections = body.allowed_sections
        # Prune allowed_pages that are now outside the new section set.
        if target.allowed_pages is not None:
            target.allowed_pages = [
                p for p in target.allowed_pages
                if PAGE_TO_SECTION.get(p) in body.allowed_sections
            ] or None
    if body.allowed_pages is not None:
        sections = body.allowed_sections if body.allowed_sections is not None else (target.allowed_sections or [])
        _validate_pages(body.allowed_pages, sections)
        target.allowed_pages = body.allowed_pages or None
    if body.write_pages is not None:
        _validate_write_pages(body.write_pages, target.allowed_pages)
        target.write_pages = body.write_pages
    # Prune write_pages that are no longer in allowed_pages (after any narrowing above).
    if target.write_pages is not None and target.allowed_pages is not None:
        pruned = [p for p in target.write_pages if p in target.allowed_pages]
        if pruned != target.write_pages:
            target.write_pages = pruned


@router.patch("/{member_id}", response_model=MemberResponse)
async def update_member(
    project_id: UUID,
    member_id: UUID,
    body: MemberUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    _project: Project = Depends(get_current_project),
    _admin: None = Depends(require_project_admin),
):
    # Try active member first
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.id == member_id,
            ProjectMember.project_id == project_id,
        )
    )
    member = result.scalar_one_or_none()
    if member:
        _apply_update(member, body)
        await db.flush()
        await db.refresh(member)
        user_result = await db.execute(select(User.email).where(User.id == member.user_id))
        email = user_result.scalar_one()
        return _member_response(member, email)

    # Try pending invitation
    result = await db.execute(
        select(ProjectInvitation).where(
            ProjectInvitation.id == member_id,
            ProjectInvitation.project_id == project_id,
        )
    )
    inv = result.scalar_one_or_none()
    if inv:
        _apply_update(inv, body)
        await db.flush()
        await db.refresh(inv)
        return _invitation_response(inv)

    raise HTTPException(status_code=404, detail="Member not found")


@router.delete("/{member_id}", status_code=204)
async def remove_member(
    project_id: UUID,
    member_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    _project: Project = Depends(get_current_project),
    _admin: None = Depends(require_project_admin),
):
    # Try active member
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.id == member_id,
            ProjectMember.project_id == project_id,
        )
    )
    member = result.scalar_one_or_none()
    if member:
        await db.delete(member)
        return None

    # Try pending invitation
    result = await db.execute(
        select(ProjectInvitation).where(
            ProjectInvitation.id == member_id,
            ProjectInvitation.project_id == project_id,
        )
    )
    inv = result.scalar_one_or_none()
    if inv:
        await db.delete(inv)
        return None

    raise HTTPException(status_code=404, detail="Member not found")
