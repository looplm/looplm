"""Tests for per-page read/write permissions."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.auth import create_access_token, hash_password
from app.models.project_member import ProjectMember
from app.models.user import User


def _valid_eval_import_body() -> dict:
    return {
        "version": "2024-01-01",
        "name": "Test Import",
        "summary": {"total": 1},
        "testCases": [{"id": "tc-1", "prompt": "q", "expectedAnswer": "a"}],
        "results": [{"id": "tc-1", "pass": True, "reason": "ok", "actualAnswer": "a"}],
    }


async def _create_member(
    db_session,
    project,
    *,
    role: str = "member",
    allowed_sections: list[str] | None = None,
    allowed_pages: list[str] | None = None,
    write_pages: list[str] | None = None,
) -> tuple[User, dict[str, str]]:
    """Create a new user + ProjectMember row, return (user, auth_headers)."""
    user = User(id=uuid4(), email=f"member-{uuid4().hex[:8]}@example.com",
                hashed_password=hash_password("pw"))
    db_session.add(user)
    await db_session.flush()

    member = ProjectMember(
        id=uuid4(),
        project_id=project.id,
        user_id=user.id,
        role=role,
        allowed_sections=allowed_sections or ["observe", "evaluate", "improve"],
        allowed_pages=allowed_pages,
        write_pages=write_pages,
    )
    db_session.add(member)
    await db_session.commit()

    token = create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


# ── Owner & admin bypass ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_can_write(client, auth_headers):
    """Project owner is not constrained by write_pages."""
    resp = await client.post("/api/evals/import", headers=auth_headers,
                             json=_valid_eval_import_body())
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_member_can_write(client, db_session, test_project):
    _, headers = await _create_member(
        db_session, test_project,
        role="admin",
        allowed_pages=["evaluations"],
        write_pages=[],  # empty but admin role bypasses the check
    )
    resp = await client.post("/api/evals/import", headers=headers,
                             json=_valid_eval_import_body())
    assert resp.status_code == 200


# ── Member write_pages semantics ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_member_legacy_null_write_pages_can_write(client, db_session, test_project):
    """Members with write_pages=null (pre-040) retain full write access."""
    _, headers = await _create_member(
        db_session, test_project,
        allowed_pages=["evaluations"],
        write_pages=None,
    )
    resp = await client.post("/api/evals/import", headers=headers,
                             json=_valid_eval_import_body())
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_member_empty_write_pages_is_read_only(client, db_session, test_project):
    """Members with write_pages=[] can read but not write."""
    _, headers = await _create_member(
        db_session, test_project,
        allowed_pages=["evaluations"],
        write_pages=[],
    )
    # Read: allowed
    resp = await client.get("/api/evals", headers=headers)
    assert resp.status_code == 200
    # Write: forbidden
    resp = await client.post("/api/evals/import", headers=headers,
                             json=_valid_eval_import_body())
    assert resp.status_code == 403
    assert "write permission" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_member_selective_write_pages(client, db_session, test_project):
    """Members with write_pages=['evaluations'] can write evals but not datasets."""
    _, headers = await _create_member(
        db_session, test_project,
        allowed_pages=["evaluations", "datasets"],
        write_pages=["evaluations"],
    )
    resp = await client.post("/api/evals/import", headers=headers,
                             json=_valid_eval_import_body())
    assert resp.status_code == 200
    # datasets write is denied
    resp = await client.post("/api/datasets", headers=headers,
                             json={"name": "X"})
    assert resp.status_code == 403


# ── Member management: invite validation & pruning ────────────────────────


@pytest.mark.asyncio
async def test_invite_rejects_write_pages_not_in_allowed_pages(
    client, auth_headers, test_project
):
    resp = await client.post(
        f"/api/projects/{test_project.id}/members",
        headers=auth_headers,
        json={
            "email": "new@example.com",
            "allowed_sections": ["evaluate"],
            "allowed_pages": ["evaluations"],
            "write_pages": ["datasets"],  # not in allowed_pages
        },
    )
    # pydantic model_validator raises 422 on invariant violation
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_invite_defaults_to_read_only_when_write_pages_omitted(
    client, auth_headers, test_project
):
    resp = await client.post(
        f"/api/projects/{test_project.id}/members",
        headers=auth_headers,
        json={
            "email": "readonly@example.com",
            "allowed_sections": ["evaluate"],
            "allowed_pages": ["evaluations", "datasets"],
        },
    )
    assert resp.status_code == 201
    assert resp.json()["write_pages"] == []


@pytest.mark.asyncio
async def test_patch_prunes_orphaned_write_pages_when_allowed_pages_narrowed(
    client, auth_headers, db_session, test_project
):
    user, _ = await _create_member(
        db_session, test_project,
        allowed_sections=["evaluate"],
        allowed_pages=["evaluations", "datasets"],
        write_pages=["evaluations", "datasets"],
    )
    # Find the member id
    from sqlalchemy import select
    result = await db_session.execute(
        select(ProjectMember).where(ProjectMember.user_id == user.id)
    )
    member = result.scalar_one()
    resp = await client.patch(
        f"/api/projects/{test_project.id}/members/{member.id}",
        headers=auth_headers,
        json={"allowed_pages": ["evaluations"]},
    )
    assert resp.status_code == 200
    assert resp.json()["write_pages"] == ["evaluations"]


@pytest.mark.asyncio
async def test_permissions_endpoint_returns_write_pages(
    client, db_session, test_project
):
    _, headers = await _create_member(
        db_session, test_project,
        allowed_pages=["evaluations"],
        write_pages=["evaluations"],
    )
    resp = await client.get("/api/me/permissions", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "member"
    assert data["allowed_pages"] == ["evaluations"]
    assert data["write_pages"] == ["evaluations"]
