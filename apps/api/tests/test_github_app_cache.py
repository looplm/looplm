"""GitHub App: installation-token cache tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.services import github_app
from app.services.github_app import (
    GithubAppCreds,
    InstallationToken,
    _INSTALLATION_TOKEN_CACHE,
    fetch_installation_token,
)


def _fake_creds(app_id: str = "123") -> GithubAppCreds:
    return GithubAppCreds(
        app_id=app_id,
        app_name="acme-app",
        client_id="Iv1.testclient",
        client_secret="shh",
        private_key="PEMBODY",
    )


@pytest.fixture(autouse=True)
def _no_env_app(monkeypatch) -> None:
    """Neutralize any instance-wide GITHUB_APP_* from a local .env."""
    for name in (
        "github_app_id",
        "github_app_name",
        "github_app_client_id",
        "github_app_client_secret",
        "github_app_private_key",
        "github_app_private_key_path",
    ):
        monkeypatch.setattr(settings, name, "")


# ── Installation token cache ─────────────────────────────────────


@pytest.mark.asyncio
async def test_installation_token_uses_cache_within_ttl(monkeypatch) -> None:
    _INSTALLATION_TOKEN_CACHE.clear()
    creds = _fake_creds()
    fake = InstallationToken(
        token="ghs_fake",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    _INSTALLATION_TOKEN_CACHE[(creds.app_id, 42)] = fake

    # No httpx mock needed: cache short-circuit fires first.
    out = await fetch_installation_token(creds, 42)
    assert out.token == "ghs_fake"


@pytest.mark.asyncio
async def test_installation_token_cache_keyed_by_app(monkeypatch) -> None:
    """Two Apps minting the same installation_id must not collide in cache."""
    _INSTALLATION_TOKEN_CACHE.clear()
    creds_a = _fake_creds("app-A")
    _INSTALLATION_TOKEN_CACHE[(creds_a.app_id, 42)] = InstallationToken(
        token="for-A",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    class _FakeResp:
        status_code = 200
        text = ""

        def json(self):
            return {
                "token": "for-B",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1))
                .isoformat()
                .replace("+00:00", "Z"),
            }

    class _FakeClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _FakeResp()

    monkeypatch.setattr(github_app, "_app_jwt", lambda creds: "jwt-test")
    monkeypatch.setattr(github_app.httpx, "AsyncClient", _FakeClient)

    creds_b = _fake_creds("app-B")
    out = await fetch_installation_token(creds_b, 42)
    assert out.token == "for-B"
    # App A's cached token is untouched.
    assert _INSTALLATION_TOKEN_CACHE[(creds_a.app_id, 42)].token == "for-A"


@pytest.mark.asyncio
async def test_installation_token_refreshes_when_expired(monkeypatch) -> None:
    _INSTALLATION_TOKEN_CACHE.clear()
    creds = _fake_creds()
    _INSTALLATION_TOKEN_CACHE[(creds.app_id, 42)] = InstallationToken(
        token="old",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    class _FakeResp:
        status_code = 200
        text = ""

        def json(self):
            return {
                "token": "ghs_new",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            }

    class _FakeClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw):
            return _FakeResp()

    monkeypatch.setattr(github_app, "_app_jwt", lambda creds: "jwt-test")
    monkeypatch.setattr(github_app.httpx, "AsyncClient", _FakeClient)

    out = await fetch_installation_token(creds, 42)
    assert out.token == "ghs_new"


def test_invalidate_caches_drops_app_entries() -> None:
    _INSTALLATION_TOKEN_CACHE.clear()
    github_app._APP_JWT_CACHE.clear()
    github_app._APP_JWT_CACHE["app-A"] = ("tok", 9999999999.0)
    github_app._APP_JWT_CACHE["app-B"] = ("tok", 9999999999.0)
    _INSTALLATION_TOKEN_CACHE[("app-A", 1)] = InstallationToken(
        token="x", expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    _INSTALLATION_TOKEN_CACHE[("app-B", 1)] = InstallationToken(
        token="y", expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    github_app.invalidate_caches("app-A")

    assert "app-A" not in github_app._APP_JWT_CACHE
    assert "app-B" in github_app._APP_JWT_CACHE
    assert ("app-A", 1) not in _INSTALLATION_TOKEN_CACHE
    assert ("app-B", 1) in _INSTALLATION_TOKEN_CACHE
