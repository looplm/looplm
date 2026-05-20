"""Tests for the GitHub App service + OAuth router + code-agent wiring."""

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
from app.models.evaluations import EvalRun
from app.models.github import GithubInstallation
from app.models.project import Project
from app.services import github_app
from app.services.github_app import (
    GithubAppError,
    InstallationToken,
    _INSTALLATION_TOKEN_CACHE,
    fetch_installation_token,
)


# ── Feature flag ─────────────────────────────────────────────────


def test_is_enabled_false_when_unconfigured() -> None:
    # The test environment leaves all github_app_* settings empty.
    assert github_app.is_enabled() is False


# ── State token ──────────────────────────────────────────────────


def test_state_token_round_trip() -> None:
    from app.routers import github_oauth

    state = github_oauth._issue_state("user-123")
    github_oauth._verify_state(state, expected_user_id="user-123")


def test_state_token_rejects_wrong_user() -> None:
    from fastapi import HTTPException

    from app.routers import github_oauth

    state = github_oauth._issue_state("user-123")
    with pytest.raises(HTTPException):
        github_oauth._verify_state(state, expected_user_id="user-456")


def test_state_token_rejects_garbage() -> None:
    from fastapi import HTTPException

    from app.routers import github_oauth

    with pytest.raises(HTTPException):
        github_oauth._verify_state("not-a-jwt", expected_user_id="user-123")


# ── Installation token cache ─────────────────────────────────────


@pytest.mark.asyncio
async def test_installation_token_uses_cache_within_ttl(monkeypatch) -> None:
    _INSTALLATION_TOKEN_CACHE.clear()
    fake = InstallationToken(
        token="ghs_fake",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    _INSTALLATION_TOKEN_CACHE[42] = fake

    # No httpx mock needed: cache short-circuit fires first.
    out = await fetch_installation_token(42)
    assert out.token == "ghs_fake"


@pytest.mark.asyncio
async def test_installation_token_refreshes_when_expired(monkeypatch) -> None:
    _INSTALLATION_TOKEN_CACHE.clear()
    _INSTALLATION_TOKEN_CACHE[42] = InstallationToken(
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

    monkeypatch.setattr(github_app, "_app_jwt", lambda: "jwt-test")
    monkeypatch.setattr(github_app.httpx, "AsyncClient", _FakeClient)

    out = await fetch_installation_token(42)
    assert out.token == "ghs_new"


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

    async def fake_token(_id):
        return InstallationToken(
            token="x",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    monkeypatch.setattr(github_app, "fetch_installation_token", fake_token)

    project_id = uuid4()
    target = await github_app.ensure_repo_clone(
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
            project_id=uuid4(),
            installation_id=1,
            repo_full_name="../etc/passwd",
        )


# ── Router endpoints ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_endpoint_reports_disabled(client) -> None:
    resp = await client.get("/api/github/status")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_auth_url_503_when_disabled(client, auth_headers) -> None:
    resp = await client.post(
        "/api/github/auth-url",
        headers=auth_headers,
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
    monkeypatch.setattr(github_app, "is_enabled", lambda: True)

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

    async def fake_ensure(*, project_id, installation_id, repo_full_name, default_branch):
        captured["installation_id"] = installation_id
        captured["repo_full_name"] = repo_full_name
        captured["default_branch"] = default_branch
        return fake_clone

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

    assert captured["installation_id"] == 99
    assert captured["repo_full_name"] == "acme/widgets"
    assert captured["default_branch"] == "main"
    assert captured["analyze_repo_path"] == str(fake_clone)

    # Cleanup
    shutil.rmtree(fake_clone, ignore_errors=True)
