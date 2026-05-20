"""GitHub App helpers — JWT signing, installation tokens, repo cloning.

All GitHub access for the Code Agent flows through here. Installation tokens
are minted on demand and cached in-process for their TTL; no GitHub-issued
secret is ever written to disk.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import httpx
from jose import jwt

from app.config import settings

logger = logging.getLogger(__name__)


class GithubAppDisabledError(RuntimeError):
    """Raised when the GitHub App feature isn't configured for this instance."""


class GithubAppError(RuntimeError):
    """Raised when a GitHub API call fails in a way we can't recover from."""


# ── Feature flag ─────────────────────────────────────────────────


def is_enabled() -> bool:
    """True when the env is configured well enough to attempt the OAuth flow."""
    return bool(
        settings.github_app_id
        and settings.github_app_client_id
        and settings.github_app_client_secret
        and _private_key_pem()
    )


def _private_key_pem() -> str | None:
    if settings.github_app_private_key:
        # Allow PEM contents pasted into .env with escaped newlines.
        return settings.github_app_private_key.replace("\\n", "\n")
    if settings.github_app_private_key_path:
        try:
            return Path(settings.github_app_private_key_path).read_text()
        except OSError as exc:
            logger.warning("Could not read GitHub App private key file: %s", exc)
            return None
    return None


# ── JWT (app-level auth) ─────────────────────────────────────────


_APP_JWT_CACHE: tuple[str, float] | None = None  # (token, expiry_epoch)


def _app_jwt() -> str:
    """Return a short-lived app-level JWT, cached in-process."""
    global _APP_JWT_CACHE
    now = time.time()
    if _APP_JWT_CACHE and _APP_JWT_CACHE[1] - 30 > now:
        return _APP_JWT_CACHE[0]

    pem = _private_key_pem()
    if not pem or not settings.github_app_id:
        raise GithubAppDisabledError("GitHub App is not configured on this instance.")

    payload = {
        "iat": int(now) - 30,          # back-date slightly to allow for clock drift
        "exp": int(now) + 9 * 60,      # 9 min (GitHub max is 10)
        "iss": settings.github_app_id,
    }
    token = jwt.encode(payload, pem, algorithm="RS256")
    _APP_JWT_CACHE = (token, payload["exp"])
    return token


# ── Installation tokens ──────────────────────────────────────────


@dataclass(frozen=True)
class InstallationToken:
    token: str
    expires_at: datetime


_INSTALLATION_TOKEN_CACHE: dict[int, InstallationToken] = {}


async def fetch_installation_token(installation_id: int) -> InstallationToken:
    """Mint (or reuse) a 1-hour installation token for the given install."""
    cached = _INSTALLATION_TOKEN_CACHE.get(installation_id)
    if cached and cached.expires_at > datetime.now(timezone.utc):
        return cached

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{settings.github_api_base_url}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {_app_jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if resp.status_code >= 400:
        raise GithubAppError(
            f"Installation token mint failed ({resp.status_code}): {resp.text[:300]}"
        )
    data = resp.json()
    token = InstallationToken(
        token=data["token"],
        expires_at=datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")),
    )
    _INSTALLATION_TOKEN_CACHE[installation_id] = token
    return token


# ── User OAuth (browser-flow step) ───────────────────────────────


async def exchange_code_for_user_token(code: str) -> str:
    """Exchange a GitHub OAuth `code` for a short-lived user access token."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{settings.github_oauth_base_url}/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_app_client_id,
                "client_secret": settings.github_app_client_secret,
                "code": code,
            },
        )
    if resp.status_code >= 400:
        raise GithubAppError(
            f"OAuth code exchange failed ({resp.status_code}): {resp.text[:300]}"
        )
    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        raise GithubAppError(f"OAuth exchange returned no token: {payload}")
    return token


async def list_user_installations(user_token: str) -> list[dict]:
    """List GitHub App installations visible to the user (filtered to our app)."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{settings.github_api_base_url}/user/installations",
            headers={
                "Authorization": f"Bearer {user_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if resp.status_code >= 400:
        raise GithubAppError(
            f"List installations failed ({resp.status_code}): {resp.text[:300]}"
        )
    return resp.json().get("installations", [])


async def list_installation_repos(installation_id: int) -> list[dict]:
    """List repos accessible to a given installation (paginated; returns all)."""
    token = (await fetch_installation_token(installation_id)).token
    repos: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=20.0) as client:
        while True:
            resp = await client.get(
                f"{settings.github_api_base_url}/installation/repositories",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                params={"per_page": 100, "page": page},
            )
            if resp.status_code >= 400:
                raise GithubAppError(
                    f"List installation repos failed ({resp.status_code}): {resp.text[:300]}"
                )
            data = resp.json()
            page_repos = data.get("repositories", [])
            repos.extend(page_repos)
            if len(page_repos) < 100:
                break
            page += 1
    return repos


# ── Repo cloning ─────────────────────────────────────────────────


_REPO_LOCKS: dict[UUID, asyncio.Lock] = {}


def _repo_lock(project_id: UUID) -> asyncio.Lock:
    lock = _REPO_LOCKS.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        _REPO_LOCKS[project_id] = lock
    return lock


def _git_env_with_token(token: str) -> dict[str, str]:
    """Build a git subprocess env that injects the auth header without touching disk."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
    env["GIT_CONFIG_VALUE_0"] = f"Authorization: bearer {token}"
    return env


async def _run_git(args: list[str], *, env: dict[str, str], cwd: Path | None = None) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        env=env,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        stderr = err.decode("utf-8", errors="replace").strip()
        raise GithubAppError(f"git {args[0]} failed: {stderr or out.decode(errors='replace')[:300]}")


def _clone_url(repo_full_name: str) -> str:
    """Compose the HTTPS clone URL for a repo. Overridable in tests via monkeypatch."""
    return f"https://github.com/{repo_full_name}.git"


async def ensure_repo_clone(
    *,
    project_id: UUID,
    installation_id: int,
    repo_full_name: str,
    default_branch: str | None = None,
) -> Path:
    """Materialize a fresh checkout of `repo_full_name` for the project.

    First run clones (shallow, single-branch). Subsequent runs `git fetch && reset --hard`.
    Returns the local path the Code Agent can read from.
    """
    if "/" not in repo_full_name or ".." in repo_full_name:
        raise GithubAppError(f"Invalid repo name: {repo_full_name!r}")

    branch = default_branch or "main"
    clone_root = Path(settings.github_clone_dir) / str(project_id)
    target = clone_root / repo_full_name.replace("/", "__")

    async with _repo_lock(project_id):
        token = (await fetch_installation_token(installation_id)).token
        env = _git_env_with_token(token)
        clone_url = _clone_url(repo_full_name)

        if (target / ".git").exists():
            # Existing clone: fetch + hard reset to the configured branch.
            await _run_git(
                ["fetch", "--depth=1", "origin", branch],
                env=env,
                cwd=target,
            )
            await _run_git(
                ["reset", "--hard", f"origin/{branch}"],
                env=env,
                cwd=target,
            )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Clean any partial leftover dir.
            if target.exists():
                shutil.rmtree(target)
            await _run_git(
                [
                    "clone",
                    "--depth=1",
                    "--single-branch",
                    "--branch",
                    branch,
                    clone_url,
                    str(target),
                ],
                env=env,
            )
        return target


def remove_repo_clone(project_id: UUID) -> None:
    """Best-effort delete of a project's clone directory."""
    clone_root = Path(settings.github_clone_dir) / str(project_id)
    if clone_root.exists():
        shutil.rmtree(clone_root, ignore_errors=True)


# ── URL helpers ──────────────────────────────────────────────────


def install_url() -> str:
    """URL where users install the App on a new org/repo."""
    if not settings.github_app_name:
        raise GithubAppDisabledError("GITHUB_APP_NAME is not set.")
    return f"{settings.github_oauth_base_url}/apps/{settings.github_app_name}/installations/new"


def authorize_url(state: str, redirect_uri: str) -> str:
    """URL to start the OAuth browser flow."""
    if not settings.github_app_client_id:
        raise GithubAppDisabledError("GITHUB_APP_CLIENT_ID is not set.")
    return (
        f"{settings.github_oauth_base_url}/login/oauth/authorize"
        f"?client_id={settings.github_app_client_id}"
        f"&state={state}"
        f"&redirect_uri={redirect_uri}"
    )
