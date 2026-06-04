"""Tests for the GitHub App service + OAuth router + code-agent wiring.

Credentials are per project: each function takes a resolved `GithubAppCreds`,
and `resolve_creds` prefers a project's own `ProjectGithubApp` row, falling back
to the instance-wide env App.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import settings
from app.encryption import encrypt_api_key
from app.models.evaluations import EvalRun
from app.models.github import GithubInstallation, ProjectGithubApp
from app.models.project import Project
from app.services import github_app
from app.services.github_app import (
    GithubAppCreds,
    GithubAppError,
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
    """Neutralize any instance-wide GITHUB_APP_* from a local .env.

    Tests here exercise the per-project path; CI has no .env so env_creds() is
    already None there. This makes the suite deterministic on dev machines too.
    """
    for name in (
        "github_app_id",
        "github_app_name",
        "github_app_client_id",
        "github_app_client_secret",
        "github_app_private_key",
        "github_app_private_key_path",
    ):
        monkeypatch.setattr(settings, name, "")


# ── Feature flag ─────────────────────────────────────────────────


def test_is_enabled_false_when_unconfigured() -> None:
    # The test environment leaves all github_app_* settings empty.
    assert github_app.env_creds() is None
    assert github_app.is_enabled(None) is False
    assert github_app.is_enabled(_fake_creds()) is True


# ── State token ──────────────────────────────────────────────────


def test_state_token_round_trip() -> None:
    from app.routers import github_oauth

    pid = uuid4()
    state = github_oauth._issue_state("user-123", pid)
    assert github_oauth._decode_state(state, expected_user_id="user-123") == pid


def test_state_token_rejects_wrong_user() -> None:
    from fastapi import HTTPException

    from app.routers import github_oauth

    state = github_oauth._issue_state("user-123", uuid4())
    with pytest.raises(HTTPException):
        github_oauth._decode_state(state, expected_user_id="user-456")


def test_state_token_rejects_garbage() -> None:
    from fastapi import HTTPException

    from app.routers import github_oauth

    with pytest.raises(HTTPException):
        github_oauth._decode_state("not-a-jwt", expected_user_id="user-123")


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


# ── Credential resolution ────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_creds_none_when_unconfigured(db_session, test_project: Project) -> None:
    creds = await github_app.resolve_creds(db_session, test_project.id)
    assert creds is None  # no project row, env empty in tests


@pytest.mark.asyncio
async def test_resolve_creds_prefers_project_row(db_session, test_project: Project) -> None:
    db_session.add(
        ProjectGithubApp(
            project_id=test_project.id,
            app_id="999",
            app_name="proj-app",
            client_id="Iv1.proj",
            client_secret=encrypt_api_key("topsecret"),
            # Stored with escaped newlines — resolve_creds should normalize them.
            private_key=encrypt_api_key("-----BEGIN-----\\nKEY\\n-----END-----"),
        )
    )
    await db_session.commit()

    creds = await github_app.resolve_creds(db_session, test_project.id)
    assert creds is not None
    assert creds.app_id == "999"
    assert creds.client_secret == "topsecret"
    assert creds.private_key == "-----BEGIN-----\nKEY\n-----END-----"
    assert github_app.is_enabled(creds) is True


# ── ensure_repo_clone against a local bare upstream ──────────────


def _make_bare_upstream(tmp_path: Path) -> Path:
    """Create a local bare repo with one initial commit on `main`."""
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@e.com"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True)
    (work / "hello.txt").write_text("hello\n")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-q", "-m", "initial"], check=True
    )
    bare = tmp_path / "upstream.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return bare


@pytest.mark.asyncio
async def test_ensure_repo_clone_creates_and_then_fetches(tmp_path, monkeypatch) -> None:
    bare = _make_bare_upstream(tmp_path)
    clone_root = tmp_path / "clones"
    clone_root.mkdir()

    monkeypatch.setattr(settings, "github_clone_dir", str(clone_root))
    monkeypatch.setattr(github_app, "_clone_url", lambda _name: f"file://{bare}")

    async def fake_token(_creds, _id):
        return InstallationToken(
            token="x",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    monkeypatch.setattr(github_app, "fetch_installation_token", fake_token)

    creds = _fake_creds()
    project_id = uuid4()
    target = await github_app.ensure_repo_clone(
        creds,
        project_id=project_id,
        installation_id=1,
        repo_full_name="acme/widgets",
        default_branch="main",
    )
    assert (target / "hello.txt").exists()
    assert (target / "hello.txt").read_text() == "hello\n"

    # Mutate upstream, then call again — should fetch + reset, not re-clone.
    work = tmp_path / "upstream-work"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@e.com"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True)
    (work / "hello.txt").write_text("hi v2\n")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-q", "-m", "update"], check=True
    )
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "main"], check=True)

    target_again = await github_app.ensure_repo_clone(
        creds,
        project_id=project_id,
        installation_id=1,
        repo_full_name="acme/widgets",
        default_branch="main",
    )
    assert target_again == target
    assert (target / "hello.txt").read_text() == "hi v2\n"


@pytest.mark.asyncio
async def test_ensure_repo_clone_rejects_traversal_in_name() -> None:
    with pytest.raises(GithubAppError):
        await github_app.ensure_repo_clone(
            _fake_creds(),
            project_id=uuid4(),
            installation_id=1,
            repo_full_name="../etc/passwd",
        )


# ── Router endpoints ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_endpoint_reports_disabled(client, auth_headers, test_project) -> None:
    resp = await client.get(
        "/api/github/status",
        headers={**auth_headers, "X-Project-Id": str(test_project.id)},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_auth_url_503_when_disabled(client, auth_headers, test_project) -> None:
    resp = await client.post(
        "/api/github/auth-url",
        headers={**auth_headers, "X-Project-Id": str(test_project.id)},
        json={"redirect_uri": "http://localhost:3100/github/callback"},
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_get_installation_returns_null_when_unset(
    client, auth_headers, test_project
) -> None:
    resp = await client.get(
        "/api/github/installation",
        headers={**auth_headers, "X-Project-Id": str(test_project.id)},
    )
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio
async def test_select_and_disconnect_lifecycle(
    client, auth_headers, test_project, db_session, monkeypatch
) -> None:
    # Pretend the App is configured so the POST passes the enabled check.
    monkeypatch.setattr(github_app, "is_enabled", lambda creds: True)

    body = {
        "installation_id": 12345,
        "account_login": "acme",
        "account_type": "Organization",
        "repo_full_name": "acme/widgets",
        "repo_default_branch": "main",
    }
    resp = await client.post(
        "/api/github/installation",
        headers={**auth_headers, "X-Project-Id": str(test_project.id)},
        json=body,
    )
    assert resp.status_code == 200
    assert resp.json()["repo_full_name"] == "acme/widgets"

    # Updating with a new repo replaces the existing row in place.
    body2 = {**body, "repo_full_name": "acme/other", "repo_default_branch": "develop"}
    resp = await client.post(
        "/api/github/installation",
        headers={**auth_headers, "X-Project-Id": str(test_project.id)},
        json=body2,
    )
    assert resp.status_code == 200

    rows = (
        await db_session.execute(
            select(GithubInstallation).where(GithubInstallation.project_id == test_project.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].repo_full_name == "acme/other"

    resp = await client.delete(
        "/api/github/installation",
        headers={**auth_headers, "X-Project-Id": str(test_project.id)},
    )
    assert resp.status_code == 204

    rows = (
        await db_session.execute(
            select(GithubInstallation).where(GithubInstallation.project_id == test_project.id)
        )
    ).scalars().all()
    assert len(rows) == 0


# ── Per-project App config CRUD ──────────────────────────────────


_FULL_APP = {
    "app_id": "123",
    "app_name": "acme-app",
    "client_id": "Iv1.testclient",
    "client_secret": "shh",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nKEYBODY\n-----END RSA PRIVATE KEY-----\n",
}


@pytest.mark.asyncio
async def test_app_config_crud_lifecycle(client, auth_headers, test_project, db_session) -> None:
    hdr = {**auth_headers, "X-Project-Id": str(test_project.id)}

    # Unconfigured: owner is allowed to manage.
    r = await client.get("/api/github/app-config", headers=hdr)
    assert r.status_code == 200
    j = r.json()
    assert j["configured"] is False
    assert j["source"] is None
    assert j["can_manage"] is True

    # Creating without secrets is rejected.
    r = await client.put(
        "/api/github/app-config",
        headers=hdr,
        json={"app_id": "123", "client_id": "Iv1.testclient"},
    )
    assert r.status_code == 400

    # Create.
    r = await client.put("/api/github/app-config", headers=hdr, json=_FULL_APP)
    assert r.status_code == 200
    j = r.json()
    assert j["configured"] is True
    assert j["source"] == "project"
    assert j["app_id"] == "123"
    assert j["app_name"] == "acme-app"
    assert j["client_id"] == "Iv1.testclient"
    assert j["has_client_secret"] is True
    assert j["has_private_key"] is True
    # Secrets are never echoed back.
    assert "client_secret" not in j
    assert "private_key" not in j

    # Stored encrypted (not plaintext) and decryptable to a usable PEM.
    row = (
        await db_session.execute(
            select(ProjectGithubApp).where(ProjectGithubApp.project_id == test_project.id)
        )
    ).scalar_one()
    assert row.client_secret != b"shh"
    creds = await github_app.resolve_creds(db_session, test_project.id)
    assert creds.client_secret == "shh"
    assert creds.private_key.startswith("-----BEGIN RSA PRIVATE KEY-----")

    # Update app_name while keeping secrets (blank secrets => keep).
    r = await client.put(
        "/api/github/app-config",
        headers=hdr,
        json={"app_id": "123", "app_name": "renamed", "client_id": "Iv1.testclient"},
    )
    assert r.status_code == 200
    assert r.json()["app_name"] == "renamed"

    # Status now reports enabled for this project.
    r = await client.get("/api/github/status", headers=hdr)
    assert r.json()["enabled"] is True
    assert r.json()["app_name"] == "renamed"

    # Delete.
    r = await client.delete("/api/github/app-config", headers=hdr)
    assert r.status_code == 204
    r = await client.get("/api/github/app-config", headers=hdr)
    assert r.json()["configured"] is False
    assert r.json()["source"] is None


@pytest.mark.asyncio
async def test_app_config_put_forbidden_for_non_admin(
    client, db_session, test_project, monkeypatch
) -> None:
    """A project member without the admin role cannot edit App credentials."""
    from app.auth import create_access_token, hash_password
    from app.models.project_member import ProjectMember
    from app.models.user import User

    member = User(
        id=uuid4(), email="member@example.com", hashed_password=hash_password("pw12345678")
    )
    db_session.add(member)
    await db_session.commit()
    db_session.add(
        ProjectMember(
            id=uuid4(),
            project_id=test_project.id,
            user_id=member.id,
            role="member",
        )
    )
    await db_session.commit()

    token = create_access_token(member.id)
    hdr = {"Authorization": f"Bearer {token}", "X-Project-Id": str(test_project.id)}

    # Can read (and is told they can't manage)...
    r = await client.get("/api/github/app-config", headers=hdr)
    assert r.status_code == 200
    assert r.json()["can_manage"] is False

    # ...but cannot write.
    r = await client.put("/api/github/app-config", headers=hdr, json=_FULL_APP)
    assert r.status_code == 403


# ── Code Agent wiring picks up the GitHub clone ──────────────────


@pytest_asyncio.fixture
async def _project_with_installation(db_session, test_project: Project) -> Project:
    db_session.add(
        GithubInstallation(
            project_id=test_project.id,
            installation_id=99,
            account_login="acme",
            account_type="Organization",
            repo_full_name="acme/widgets",
            repo_default_branch="main",
        )
    )
    await db_session.commit()
    return test_project


@pytest.mark.asyncio
async def test_code_agent_trigger_uses_github_clone(
    client,
    auth_headers,
    db_session,
    _project_with_installation: Project,
    monkeypatch,
    tmp_path,
) -> None:
    project = _project_with_installation

    # The frontend won't have set code_agent_api_key in this test; we don't
    # actually run the agent — just verify the trigger endpoint resolved the
    # repo path from the installation. The background task will fail at the
    # _build_model step, but the trigger response is still 202.
    project.settings = {
        "code_agent_provider": "openai",
        "code_agent_api_key": "sk-test",
    }
    await db_session.commit()

    captured: dict[str, object] = {}

    fake_clone = tmp_path / "fake-clone"
    fake_clone.mkdir()
    (fake_clone / "README.md").write_text("hi\n")

    creds = _fake_creds()

    async def fake_resolve(_db, _project_id):
        return creds

    async def fake_ensure(passed_creds, *, project_id, installation_id, repo_full_name, default_branch):
        captured["creds_app_id"] = passed_creds.app_id
        captured["installation_id"] = installation_id
        captured["repo_full_name"] = repo_full_name
        captured["default_branch"] = default_branch
        return fake_clone

    monkeypatch.setattr(github_app, "resolve_creds", fake_resolve)
    monkeypatch.setattr(github_app, "is_enabled", lambda c: True)
    monkeypatch.setattr(github_app, "ensure_repo_clone", fake_ensure)

    # Prevent the background task from actually running the agent.
    async def fake_analyze(**_kwargs):
        captured["analyze_repo_path"] = _kwargs.get("repo_path")

    from app.routers import code_agent as code_agent_router

    monkeypatch.setattr(code_agent_router, "analyze_eval_run", fake_analyze)

    run = EvalRun(
        id=uuid4(), project_id=project.id, name="r", total=0, passed=0, failed=0
    )
    db_session.add(run)
    await db_session.commit()

    resp = await client.post(
        f"/api/code-agent/{run.id}/analyze",
        headers={**auth_headers, "X-Project-Id": str(project.id)},
        json={"analysis_mode": "quick"},
    )
    assert resp.status_code == 202

    # Let the background task fire.
    import asyncio
    await asyncio.sleep(0)

    assert captured["creds_app_id"] == "123"
    assert captured["installation_id"] == 99
    assert captured["repo_full_name"] == "acme/widgets"
    assert captured["default_branch"] == "main"
    assert captured["analyze_repo_path"] == str(fake_clone)

    # Cleanup
    shutil.rmtree(fake_clone, ignore_errors=True)
