"""GitHub App browser-auth flow + repo linking for the Code Agent.

Credentials are per project: each project may configure its own GitHub App
(see the `/app-config` endpoints), and projects without one fall back to the
instance-wide `GITHUB_APP_*` env App. Every flow resolves the acting project's
credentials via `github_app.resolve_creds` before talking to GitHub.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    ALGORITHM,
    get_current_project,
    get_current_user,
    require_project_admin,
)
from app.config import settings
from app.db import get_db
from app.encryption import encrypt_api_key
from app.models.github import GithubInstallation, ProjectGithubApp
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.services import github_app

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/github", tags=["github"])

_STATE_TTL_SECONDS = 600  # 10 min — the user has to finish the GitHub flow within this.


# ── Schemas ──────────────────────────────────────────────────────


class StatusResponse(BaseModel):
    enabled: bool
    app_name: str | None = None
    install_url: str | None = None


class AuthUrlRequest(BaseModel):
    redirect_uri: str


class AuthUrlResponse(BaseModel):
    url: str


class CallbackRequest(BaseModel):
    code: str
    state: str


class CallbackInstallation(BaseModel):
    installation_id: int
    account_login: str
    account_type: str


class CallbackResponse(BaseModel):
    installations: list[CallbackInstallation]


class SelectInstallationRequest(BaseModel):
    installation_id: int
    account_login: str
    account_type: str
    repo_full_name: str
    repo_default_branch: str | None = None


class InstallationResponse(BaseModel):
    installation_id: int
    account_login: str
    account_type: str
    repo_full_name: str | None
    repo_default_branch: str | None

    model_config = {"from_attributes": True}


class RepoListItem(BaseModel):
    full_name: str
    default_branch: str
    private: bool


class AppConfigResponse(BaseModel):
    """Per-project App config metadata. Never includes secret values."""

    configured: bool  # project has its own ProjectGithubApp row
    source: str | None  # "project" | "env" | None
    can_manage: bool  # current user may edit (project owner/admin)
    app_id: str | None = None
    app_name: str | None = None
    client_id: str | None = None
    has_client_secret: bool = False
    has_private_key: bool = False


class AppConfigUpsertRequest(BaseModel):
    app_id: str
    app_name: str | None = None
    client_id: str
    # Write-only secrets. On update, leave blank/omit to keep the stored value.
    client_secret: str | None = None
    private_key: str | None = None


# ── State token (signed, short-lived) ────────────────────────────


def _issue_state(user_id: str, project_id: UUID) -> str:
    payload = {
        "sub": user_id,
        "pid": str(project_id),
        "kind": "github_oauth_state",
        "nonce": secrets.token_hex(8),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=_STATE_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.api_secret_key, algorithm=ALGORITHM)


def _decode_state(state: str, expected_user_id: str) -> UUID:
    """Verify the state token and return the project_id it was issued for."""
    try:
        payload = jwt.decode(state, settings.api_secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid OAuth state: {exc}") from exc
    if payload.get("kind") != "github_oauth_state":
        raise HTTPException(status_code=400, detail="Invalid OAuth state kind")
    if str(payload.get("sub")) != str(expected_user_id):
        raise HTTPException(status_code=400, detail="OAuth state does not match user")
    pid = payload.get("pid")
    if not pid:
        raise HTTPException(status_code=400, detail="OAuth state missing project")
    try:
        return UUID(str(pid))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="OAuth state has invalid project") from exc


async def _is_project_admin(db: AsyncSession, user: User, project: Project) -> bool:
    """Mirror `require_project_admin` as a boolean (owner or admin member)."""
    if project.owner_id == user.id:
        return True
    member = (
        await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    return bool(member and member.role == "admin")


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/status", response_model=StatusResponse)
async def github_status(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
) -> StatusResponse:
    """Tells the frontend whether GitHub is usable for the current project."""
    creds = await github_app.resolve_creds(db, project.id)
    if not github_app.is_enabled(creds):
        return StatusResponse(enabled=False)
    try:
        install_url = github_app.install_url(creds)
    except github_app.GithubAppDisabledError:
        install_url = None
    return StatusResponse(
        enabled=True,
        app_name=creds.app_name or None,
        install_url=install_url,
    )


@router.post("/auth-url", response_model=AuthUrlResponse)
async def github_auth_url(
    body: AuthUrlRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
) -> AuthUrlResponse:
    """Return the GitHub authorize URL the frontend should redirect the user to."""
    creds = await github_app.resolve_creds(db, project.id)
    if not github_app.is_enabled(creds):
        raise HTTPException(status_code=503, detail="GitHub App not configured")
    state = _issue_state(str(user.id), project.id)
    url = github_app.authorize_url(creds, state=state, redirect_uri=body.redirect_uri)
    return AuthUrlResponse(url=url)


@router.post("/callback", response_model=CallbackResponse)
async def github_callback(
    body: CallbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CallbackResponse:
    """Finish the browser flow: exchange the code, list installations.

    The project is taken from the signed state (authoritative), so the right
    App credentials are used even if the active project changed in the UI. The
    user OAuth token is used once here and discarded; everything else uses
    short-lived installation tokens.
    """
    project_id = _decode_state(body.state, expected_user_id=str(user.id))
    creds = await github_app.resolve_creds(db, project_id)
    if not github_app.is_enabled(creds):
        raise HTTPException(status_code=503, detail="GitHub App not configured")
    try:
        user_token = await github_app.exchange_code_for_user_token(creds, body.code)
        installs = await github_app.list_user_installations(user_token)
    except github_app.GithubAppError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return CallbackResponse(
        installations=[
            CallbackInstallation(
                installation_id=item["id"],
                account_login=item["account"]["login"],
                account_type=item["account"].get("type", "User"),
            )
            for item in installs
        ]
    )


@router.get("/installations/{installation_id}/repos", response_model=list[RepoListItem])
async def list_repos(
    installation_id: int,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _user: User = Depends(get_current_user),
) -> list[RepoListItem]:
    creds = await github_app.resolve_creds(db, project.id)
    if not github_app.is_enabled(creds):
        raise HTTPException(status_code=503, detail="GitHub App not configured")
    try:
        repos = await github_app.list_installation_repos(creds, installation_id)
    except github_app.GithubAppError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [
        RepoListItem(
            full_name=r["full_name"],
            default_branch=r.get("default_branch") or "main",
            private=r.get("private", False),
        )
        for r in repos
    ]


@router.get("/installation", response_model=InstallationResponse | None)
async def get_installation(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
) -> Any:
    row = (
        await db.execute(
            select(GithubInstallation).where(GithubInstallation.project_id == project.id)
        )
    ).scalar_one_or_none()
    return row  # FastAPI serializes via from_attributes; None becomes JSON null


@router.post("/installation", response_model=InstallationResponse)
async def select_installation(
    body: SelectInstallationRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _user: User = Depends(get_current_user),
) -> GithubInstallation:
    creds = await github_app.resolve_creds(db, project.id)
    if not github_app.is_enabled(creds):
        raise HTTPException(status_code=503, detail="GitHub App not configured")

    existing = (
        await db.execute(
            select(GithubInstallation).where(GithubInstallation.project_id == project.id)
        )
    ).scalar_one_or_none()

    if existing:
        existing.installation_id = body.installation_id
        existing.account_login = body.account_login
        existing.account_type = body.account_type
        existing.repo_full_name = body.repo_full_name
        existing.repo_default_branch = body.repo_default_branch
        existing.updated_at = datetime.now(timezone.utc)
        row = existing
    else:
        row = GithubInstallation(
            project_id=project.id,
            installation_id=body.installation_id,
            account_login=body.account_login,
            account_type=body.account_type,
            repo_full_name=body.repo_full_name,
            repo_default_branch=body.repo_default_branch,
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/installation", status_code=204)
async def disconnect_installation(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _user: User = Depends(get_current_user),
) -> None:
    row = (
        await db.execute(
            select(GithubInstallation).where(GithubInstallation.project_id == project.id)
        )
    ).scalar_one_or_none()
    if not row:
        return
    await db.delete(row)
    await db.commit()
    github_app.remove_repo_clone(project.id)


# ── Per-project App configuration ────────────────────────────────


async def _load_project_app(db: AsyncSession, project_id: UUID) -> ProjectGithubApp | None:
    return (
        await db.execute(
            select(ProjectGithubApp).where(ProjectGithubApp.project_id == project_id)
        )
    ).scalar_one_or_none()


def _app_config_response(
    row: ProjectGithubApp | None, *, can_manage: bool
) -> AppConfigResponse:
    if row is not None:
        return AppConfigResponse(
            configured=True,
            source="project",
            can_manage=can_manage,
            app_id=row.app_id,
            app_name=row.app_name,
            client_id=row.client_id,
            has_client_secret=True,
            has_private_key=True,
        )
    env = github_app.env_creds()
    if env is not None:
        # Inherited instance-wide App: show non-secret fields for context.
        return AppConfigResponse(
            configured=False,
            source="env",
            can_manage=can_manage,
            app_id=env.app_id,
            app_name=env.app_name or None,
            client_id=env.client_id,
            has_client_secret=True,
            has_private_key=True,
        )
    return AppConfigResponse(configured=False, source=None, can_manage=can_manage)


@router.get("/app-config", response_model=AppConfigResponse)
async def get_app_config(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
) -> AppConfigResponse:
    row = await _load_project_app(db, project.id)
    can_manage = await _is_project_admin(db, user, project)
    return _app_config_response(row, can_manage=can_manage)


@router.put("/app-config", response_model=AppConfigResponse)
async def upsert_app_config(
    body: AppConfigUpsertRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _admin: None = Depends(require_project_admin),
) -> AppConfigResponse:
    row = await _load_project_app(db, project.id)

    if row is None:
        if not (body.client_secret and body.private_key):
            raise HTTPException(
                status_code=400,
                detail="client_secret and private_key are required when first configuring the App.",
            )
        row = ProjectGithubApp(
            project_id=project.id,
            app_id=body.app_id,
            app_name=body.app_name,
            client_id=body.client_id,
            client_secret=encrypt_api_key(body.client_secret),
            private_key=encrypt_api_key(body.private_key),
        )
        db.add(row)
    else:
        old_app_id = row.app_id
        row.app_id = body.app_id
        row.app_name = body.app_name
        row.client_id = body.client_id
        if body.client_secret:
            row.client_secret = encrypt_api_key(body.client_secret)
        if body.private_key:
            row.private_key = encrypt_api_key(body.private_key)
        row.updated_at = datetime.now(timezone.utc)
        github_app.invalidate_caches(old_app_id)

    await db.commit()
    await db.refresh(row)
    github_app.invalidate_caches(row.app_id)
    return _app_config_response(row, can_manage=True)


@router.delete("/app-config", status_code=204)
async def delete_app_config(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    _admin: None = Depends(require_project_admin),
) -> None:
    row = await _load_project_app(db, project.id)
    if row is None:
        return
    app_id = row.app_id
    await db.delete(row)
    await db.commit()
    github_app.invalidate_caches(app_id)
