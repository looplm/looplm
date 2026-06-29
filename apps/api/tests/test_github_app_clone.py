"""GitHub App: ensure_repo_clone against a local bare upstream."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.config import settings
from app.services import github_app
from app.services.github_app import (
    GithubAppCreds,
    GithubAppError,
    InstallationToken,
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
