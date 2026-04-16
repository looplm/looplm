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


def _member_response(member: ProjectMember, email: str) -> MemberResponse:
    return MemberResponse(
        id=member.id,
        user_id=member.user_id,
        email=email,
        role=member.role,
        allowed_sections=member.allowed_sections or [],
        allowed_pages=member.allowed_pages,
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
        status="pending",
        created_at=inv.created_at,
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
    # Active members
    result = await db.execute(
        select(ProjectMember, User.email)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.created_at.asc())
    )
    members = [_member_response(m, email) for m, email in result.all()]

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
        status="pending",
        invite_link=invite_url,
        email_sent=email_sent,
    )


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
        if body.role is not None:
            member.role = body.role
        if body.allowed_sections is not None:
            invalid = set(body.allowed_sections) - set(ALL_SECTIONS)
            if invalid:
                raise HTTPException(status_code=400, detail=f"Invalid sections: {', '.join(invalid)}")
            member.allowed_sections = body.allowed_sections
            # Remove orphaned pages when sections are narrowed
            if member.allowed_pages is not None:
                member.allowed_pages = [
                    p for p in member.allowed_pages if PAGE_TO_SECTION.get(p) in body.allowed_sections
                ] or None
        if body.allowed_pages is not None:
            sections = body.allowed_sections if body.allowed_sections is not None else (member.allowed_sections or [])
            _validate_pages(body.allowed_pages, sections)
            member.allowed_pages = body.allowed_pages or None
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
        if body.role is not None:
            inv.role = body.role
        if body.allowed_sections is not None:
            invalid = set(body.allowed_sections) - set(ALL_SECTIONS)
            if invalid:
                raise HTTPException(status_code=400, detail=f"Invalid sections: {', '.join(invalid)}")
            inv.allowed_sections = body.allowed_sections
            if inv.allowed_pages is not None:
                inv.allowed_pages = [
                    p for p in inv.allowed_pages if PAGE_TO_SECTION.get(p) in body.allowed_sections
                ] or None
        if body.allowed_pages is not None:
            sections = body.allowed_sections if body.allowed_sections is not None else (inv.allowed_sections or [])
            _validate_pages(body.allowed_pages, sections)
            inv.allowed_pages = body.allowed_pages or None
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
