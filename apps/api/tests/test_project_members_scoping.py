"""Tenancy regression tests for /api/projects/{project_id}/members.

The router authorized against the X-Project-Id header while querying by the path parameter, so
an admin of any project could read and write the membership of any other. Every case here sends
a header naming a project the caller legitimately administers and a path naming someone else's.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.auth import create_access_token, hash_password
from app.models.project import Project
from app.models.project_invitation import ProjectInvitation
from app.models.project_member import ProjectMember
from app.models.user import User


async def _other_tenant(db_session) -> tuple[User, Project, ProjectMember]:
    """A second tenant: its own owner, project, and one member row to target."""
    owner = User(id=uuid4(), email=f"other-owner-{uuid4().hex[:8]}@example.com",
                 hashed_password=hash_password("pw"))
    victim = User(id=uuid4(), email=f"victim-{uuid4().hex[:8]}@example.com",
                  hashed_password=hash_password("pw"))
    db_session.add_all([owner, victim])
    await db_session.flush()

    project = Project(id=uuid4(), owner_id=owner.id, name="Other Tenant")
    db_session.add(project)
    await db_session.flush()

    member = ProjectMember(
        id=uuid4(),
        project_id=project.id,
        user_id=victim.id,
        role="member",
        allowed_sections=["observe"],
        allowed_pages=["traces"],
        write_pages=[],
    )
    db_session.add(member)
    await db_session.flush()
    return owner, project, member


def _headers(user: User, header_project: Project) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user.id)}",
        "X-Project-Id": str(header_project.id),
    }


@pytest.mark.asyncio
async def test_list_members_of_foreign_project_is_404(
    client, db_session, test_user, test_project
):
    _owner, other, _member = await _other_tenant(db_session)
    resp = await client.get(
        f"/api/projects/{other.id}/members", headers=_headers(test_user, test_project)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_self_escalation_into_foreign_project_is_blocked(
    client, db_session, test_user, test_project
):
    _owner, other, _member = await _other_tenant(db_session)
    resp = await client.post(
        f"/api/projects/{other.id}/members",
        headers=_headers(test_user, test_project),
        json={
            "email": test_user.email,
            "role": "admin",
            "allowed_sections": ["observe", "evaluate", "improve"],
        },
    )
    assert resp.status_code == 404

    granted = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == other.id,
                ProjectMember.user_id == test_user.id,
            )
        )
    ).scalar_one_or_none()
    assert granted is None


@pytest.mark.asyncio
async def test_patch_foreign_member_is_404(client, db_session, test_user, test_project):
    _owner, other, member = await _other_tenant(db_session)
    resp = await client.patch(
        f"/api/projects/{other.id}/members/{member.id}",
        headers=_headers(test_user, test_project),
        json={"role": "admin"},
    )
    assert resp.status_code == 404
    await db_session.refresh(member)
    assert member.role == "member"


@pytest.mark.asyncio
async def test_delete_foreign_member_is_404(client, db_session, test_user, test_project):
    _owner, other, member = await _other_tenant(db_session)
    resp = await client.delete(
        f"/api/projects/{other.id}/members/{member.id}",
        headers=_headers(test_user, test_project),
    )
    assert resp.status_code == 404
    still_there = (
        await db_session.execute(select(ProjectMember).where(ProjectMember.id == member.id))
    ).scalar_one_or_none()
    assert still_there is not None


@pytest.mark.asyncio
async def test_foreign_invitations_are_not_listed(
    client, db_session, test_user, test_project
):
    _owner, other, _member = await _other_tenant(db_session)
    db_session.add(
        ProjectInvitation(
            id=uuid4(),
            project_id=other.id,
            invited_by=_owner.id,
            email="pending@other-tenant.example",
            token=uuid4().hex,
            role="member",
            allowed_sections=["observe"],
        )
    )
    await db_session.flush()

    resp = await client.get(
        f"/api/projects/{other.id}/members", headers=_headers(test_user, test_project)
    )
    assert resp.status_code == 404

    # And the caller's own project listing must not leak it either.
    resp = await client.get(
        f"/api/projects/{test_project.id}/members", headers=_headers(test_user, test_project)
    )
    assert resp.status_code == 200
    emails = {row["email"] for row in resp.json()["data"]}
    assert "pending@other-tenant.example" not in emails


@pytest.mark.asyncio
async def test_path_wins_over_a_stale_header(client, test_user, test_project):
    """A stale X-Project-Id must not break access to the project named in the path."""
    resp = await client.get(
        f"/api/projects/{test_project.id}/members",
        headers={
            "Authorization": f"Bearer {create_access_token(test_user.id)}",
            "X-Project-Id": str(uuid4()),
        },
    )
    assert resp.status_code == 200
