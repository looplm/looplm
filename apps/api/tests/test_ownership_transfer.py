"""Tests for the project owner appearing in the member list and ownership transfer."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.auth import create_access_token, hash_password
from app.models.project_member import ProjectMember
from app.models.user import User


async def _create_member(db_session, project, *, role: str = "member"):
    """Create a user + ProjectMember row, return (user, auth_headers)."""
    user = User(
        id=uuid4(),
        email=f"member-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        ProjectMember(
            id=uuid4(),
            project_id=project.id,
            user_id=user.id,
            role=role,
            allowed_sections=["observe", "evaluate", "improve"],
        )
    )
    await db_session.commit()
    return user, {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.mark.asyncio
async def test_owner_appears_in_member_list(client, auth_headers, test_user, test_project):
    resp = await client.get(
        f"/api/projects/{test_project.id}/members", headers=auth_headers
    )
    assert resp.status_code == 200
    rows = resp.json()["data"]
    owner_rows = [r for r in rows if r["role"] == "owner"]
    assert len(owner_rows) == 1
    owner = owner_rows[0]
    assert owner["email"] == test_user.email
    assert owner["user_id"] == str(test_project.owner_id)
    assert owner["status"] == "active"


@pytest.mark.asyncio
async def test_transfer_promotes_member_and_demotes_owner(
    client, auth_headers, db_session, test_user, test_project
):
    new_owner, new_owner_headers = await _create_member(db_session, test_project)

    resp = await client.post(
        f"/api/projects/{test_project.id}/transfer-ownership",
        headers=auth_headers,
        json={"new_owner_id": str(new_owner.id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_id"] == str(new_owner.id)

    # The member list, viewed by the new owner, shows them as owner and the
    # previous owner demoted to an admin member (exactly once each).
    resp = await client.get(
        f"/api/projects/{test_project.id}/members", headers=new_owner_headers
    )
    assert resp.status_code == 200
    rows = resp.json()["data"]
    by_user = {r["user_id"]: r for r in rows if r["user_id"]}
    assert by_user[str(new_owner.id)]["role"] == "owner"
    assert by_user[str(test_user.id)]["role"] == "admin"
    # New owner is not also listed as a plain member row.
    assert sum(1 for r in rows if r["user_id"] == str(new_owner.id)) == 1


@pytest.mark.asyncio
async def test_transfer_requires_owner(
    client, db_session, test_project
):
    _, admin_headers = await _create_member(db_session, test_project, role="admin")
    other, _ = await _create_member(db_session, test_project)

    resp = await client.post(
        f"/api/projects/{test_project.id}/transfer-ownership",
        headers=admin_headers,
        json={"new_owner_id": str(other.id)},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_transfer_to_nonmember_rejected(client, auth_headers, test_project):
    resp = await client.post(
        f"/api/projects/{test_project.id}/transfer-ownership",
        headers=auth_headers,
        json={"new_owner_id": str(uuid4())},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_transfer_to_self_rejected(client, auth_headers, test_user, test_project):
    resp = await client.post(
        f"/api/projects/{test_project.id}/transfer-ownership",
        headers=auth_headers,
        json={"new_owner_id": str(test_user.id)},
    )
    assert resp.status_code == 400
