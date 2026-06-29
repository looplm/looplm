"""GitHub App: OAuth router endpoints, per-project App config CRUD, and
code-agent wiring tests."""

from __future__ import annotations

import shutil
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import settings
from app.models.evaluations import EvalRun
from app.models.github import GithubInstallation, ProjectGithubApp
from app.models.project import Project
from app.services import github_app
from app.services.github_app import GithubAppCreds


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
