"""GitHub App: feature flag, state token, and credential resolution tests.

Credentials are per project: each function takes a resolved `GithubAppCreds`,
and `resolve_creds` prefers a project's own `ProjectGithubApp` row, falling back
to the instance-wide env App.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.config import settings
from app.encryption import encrypt_api_key
from app.models.github import ProjectGithubApp
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
