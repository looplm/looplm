"""Tests for the user directory — named identities and groups of end users."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.auth import create_access_token, hash_password
from app.models.project_member import ProjectMember
from app.models.user import User

IDENTITIES = "/api/user-identities"
GROUPS = "/api/user-groups"


async def _create_identity(client, auth_headers, name: str, user_ids: list[str]) -> dict:
    resp = await client.post(
        IDENTITIES, headers=auth_headers, json={"name": name, "user_ids": user_ids}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Identities ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_list_identity(client, auth_headers):
    created = await _create_identity(client, auth_headers, "Ada", ["u-1", "u-2"])
    assert created["name"] == "Ada"
    assert created["user_ids"] == ["u-1", "u-2"]

    resp = await client.get(IDENTITIES, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["data"][0]["id"] == created["id"]


@pytest.mark.asyncio
async def test_create_identity_strips_blanks_and_duplicates(client, auth_headers):
    created = await _create_identity(client, auth_headers, "Ada", [" u-1 ", "u-1", "", "u-2"])
    assert created["user_ids"] == ["u-1", "u-2"]


@pytest.mark.asyncio
async def test_duplicate_identity_name_conflicts(client, auth_headers):
    await _create_identity(client, auth_headers, "Ada", ["u-1"])
    resp = await client.post(IDENTITIES, headers=auth_headers, json={"name": "Ada"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"]["code"] == "DUPLICATE"


@pytest.mark.asyncio
async def test_user_id_cannot_belong_to_two_identities(client, auth_headers):
    await _create_identity(client, auth_headers, "Ada", ["u-1"])
    resp = await client.post(
        IDENTITIES, headers=auth_headers, json={"name": "Grace", "user_ids": ["u-1"]}
    )
    assert resp.status_code == 409
    assert "Ada" in resp.json()["detail"]["error"]["message"]


@pytest.mark.asyncio
async def test_update_identity_keeps_its_own_user_ids(client, auth_headers):
    identity = await _create_identity(client, auth_headers, "Ada", ["u-1"])
    resp = await client.patch(
        f"{IDENTITIES}/{identity['id']}",
        headers=auth_headers,
        json={"name": "Ada L.", "user_ids": ["u-1", "u-3"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Ada L."
    assert resp.json()["user_ids"] == ["u-1", "u-3"]


@pytest.mark.asyncio
async def test_update_identity_rejects_claimed_user_id(client, auth_headers):
    await _create_identity(client, auth_headers, "Ada", ["u-1"])
    grace = await _create_identity(client, auth_headers, "Grace", ["u-2"])
    resp = await client.patch(
        f"{IDENTITIES}/{grace['id']}", headers=auth_headers, json={"user_ids": ["u-1"]}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_identity_rejects_empty_name(client, auth_headers):
    identity = await _create_identity(client, auth_headers, "Ada", [])
    resp = await client.patch(
        f"{IDENTITIES}/{identity['id']}", headers=auth_headers, json={"name": "   "}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_unknown_identity_is_404(client, auth_headers):
    resp = await client.patch(f"{IDENTITIES}/{uuid4()}", headers=auth_headers, json={"name": "X"})
    assert resp.status_code == 404
    # The app-level 404 handler replaces the body, so only the envelope shape is asserted here.
    assert resp.json()["error"]["code"] == "NOT_FOUND"


# ── Groups ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_group_with_members(client, auth_headers):
    identity = await _create_identity(client, auth_headers, "Ada", ["u-1"])
    resp = await client.post(
        GROUPS,
        headers=auth_headers,
        json={
            "name": "Internal QA",
            "description": "Staff accounts",
            "identity_ids": [identity["id"]],
            "user_ids": ["qa-bot"],
        },
    )
    assert resp.status_code == 201, resp.text
    group = resp.json()
    assert group["identity_ids"] == [identity["id"]]
    assert group["user_ids"] == ["qa-bot"]
    assert group["description"] == "Staff accounts"


@pytest.mark.asyncio
async def test_group_rejects_unknown_identity(client, auth_headers):
    resp = await client.post(
        GROUPS, headers=auth_headers, json={"name": "Internal", "identity_ids": [str(uuid4())]}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_group_name_conflicts(client, auth_headers):
    await client.post(GROUPS, headers=auth_headers, json={"name": "Internal"})
    resp = await client.post(GROUPS, headers=auth_headers, json={"name": "Internal"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_group_membership(client, auth_headers):
    created = await client.post(GROUPS, headers=auth_headers, json={"name": "Internal"})
    group_id = created.json()["id"]
    resp = await client.patch(
        f"{GROUPS}/{group_id}", headers=auth_headers, json={"user_ids": ["qa-1", "qa-1", " qa-2 "]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user_ids"] == ["qa-1", "qa-2"]


@pytest.mark.asyncio
async def test_delete_identity_prunes_group_membership(client, auth_headers):
    identity = await _create_identity(client, auth_headers, "Ada", ["u-1"])
    created = await client.post(
        GROUPS,
        headers=auth_headers,
        json={"name": "Internal", "identity_ids": [identity["id"]], "user_ids": ["qa-1"]},
    )
    group_id = created.json()["id"]

    resp = await client.delete(f"{IDENTITIES}/{identity['id']}", headers=auth_headers)
    assert resp.status_code == 204

    groups = (await client.get(GROUPS, headers=auth_headers)).json()["data"]
    group = next(g for g in groups if g["id"] == group_id)
    assert group["identity_ids"] == []
    assert group["user_ids"] == ["qa-1"]


@pytest.mark.asyncio
async def test_delete_group_keeps_identities(client, auth_headers):
    identity = await _create_identity(client, auth_headers, "Ada", ["u-1"])
    created = await client.post(
        GROUPS, headers=auth_headers, json={"name": "Internal", "identity_ids": [identity["id"]]}
    )
    resp = await client.delete(f"{GROUPS}/{created.json()['id']}", headers=auth_headers)
    assert resp.status_code == 204

    identities = (await client.get(IDENTITIES, headers=auth_headers)).json()
    assert identities["total"] == 1


# ── Permissions ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_member_without_write_cannot_edit_directory(client, db_session, test_project):
    """Read-only Observe access can list the directory but not change it."""
    user = User(
        id=uuid4(), email=f"member-{uuid4().hex[:8]}@example.com", hashed_password=hash_password("pw")
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        ProjectMember(
            id=uuid4(),
            project_id=test_project.id,
            user_id=user.id,
            role="member",
            allowed_sections=["observe"],
            allowed_pages=["traces"],
            write_pages=[],
        )
    )
    await db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    assert (await client.get(IDENTITIES, headers=headers)).status_code == 200
    resp = await client.post(IDENTITIES, headers=headers, json={"name": "Ada"})
    assert resp.status_code == 403
