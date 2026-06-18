"""Tests for authentication endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from jose import jwt

from app.auth import ALGORITHM
from app.config import settings


def _assert_token_response(data: dict) -> None:
    """Assert common fields on any token response."""
    assert "access_token" in data
    assert "refresh_token" in data
    assert "expires_in" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 3600


@pytest.mark.asyncio
async def test_register(client: AsyncClient):
    resp = await client.post("/api/auth/register", json={"email": "new@example.com", "password": "securepass1"})
    assert resp.status_code == 201
    _assert_token_response(resp.json())


@pytest.mark.asyncio
async def test_first_user_gets_default_project(client: AsyncClient):
    """The very first sign-up is the platform admin and is bootstrapped with a project."""
    resp = await client.post(
        "/api/auth/register", json={"email": "first@example.com", "password": "securepass1"}
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    projects = await client.get("/api/projects", headers=headers)
    assert projects.status_code == 200
    assert len(projects.json()["data"]) == 1

    me = await client.get("/api/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "first@example.com"
    assert me.json()["is_platform_admin"] is True


@pytest.mark.asyncio
async def test_regular_signup_gets_no_project_and_cannot_create(client: AsyncClient):
    """A non-admin sign-up lands in no project and cannot create one."""
    # First user becomes the platform admin (bootstrapped with a project).
    await client.post(
        "/api/auth/register", json={"email": "admin@example.com", "password": "securepass1"}
    )
    # Second user is a regular sign-up.
    resp = await client.post(
        "/api/auth/register", json={"email": "regular@example.com", "password": "securepass1"}
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    projects = await client.get("/api/projects", headers=headers)
    assert projects.status_code == 200
    assert projects.json()["data"] == []

    me = await client.get("/api/me", headers=headers)
    assert me.json()["is_platform_admin"] is False

    create = await client.post(
        "/api/projects", headers=headers, json={"name": "Mine"}
    )
    assert create.status_code == 403


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    # Register first
    await client.post("/api/auth/register", json={"email": "login@example.com", "password": "securepass1"})
    resp = await client.post("/api/auth/login", json={"email": "login@example.com", "password": "securepass1"})
    assert resp.status_code == 200
    _assert_token_response(resp.json())


@pytest.mark.asyncio
async def test_duplicate_registration(client: AsyncClient):
    await client.post("/api/auth/register", json={"email": "dupe@example.com", "password": "securepass1"})
    resp = await client.post("/api/auth/register", json={"email": "dupe@example.com", "password": "securepass1"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_wrong_password(client: AsyncClient):
    await client.post("/api/auth/register", json={"email": "wp@example.com", "password": "securepass1"})
    resp = await client.post("/api/auth/login", json={"email": "wp@example.com", "password": "wrongpassword"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    resp = await client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever1"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_no_token(client: AsyncClient):
    resp = await client.get("/api/prompts")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_protected_endpoint_bad_token(client: AsyncClient):
    resp = await client.get("/api/prompts", headers={"Authorization": "Bearer invalidtoken"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_short_password_rejected(client: AsyncClient):
    resp = await client.post("/api/auth/register", json={"email": "short@example.com", "password": "abc"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_email_rejected(client: AsyncClient):
    resp = await client.post("/api/auth/register", json={"email": "not-an-email", "password": "securepass1"})
    assert resp.status_code == 422


# --- Refresh token tests ---


@pytest.mark.asyncio
async def test_refresh_happy_path(client: AsyncClient):
    reg = await client.post("/api/auth/register", json={"email": "refresh@example.com", "password": "securepass1"})
    refresh_token = reg.json()["refresh_token"]

    resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    data = resp.json()
    _assert_token_response(data)
    # New tokens should differ from original
    assert data["refresh_token"] != refresh_token


@pytest.mark.asyncio
async def test_refresh_invalid_token(client: AsyncClient):
    resp = await client.post("/api/auth/refresh", json={"refresh_token": "not.a.valid.token"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_expired_token(client: AsyncClient):
    # Craft an expired refresh token
    payload = {"sub": "00000000-0000-0000-0000-000000000000", "type": "refresh", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}
    expired = jwt.encode(payload, settings.api_secret_key, algorithm=ALGORITHM)

    resp = await client.post("/api/auth/refresh", json={"refresh_token": expired})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_access_token_rejected(client: AsyncClient):
    """Using an access token as a refresh token should fail."""
    reg = await client.post("/api/auth/register", json={"email": "wrongtype@example.com", "password": "securepass1"})
    access_token = reg.json()["access_token"]

    resp = await client.post("/api/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401
