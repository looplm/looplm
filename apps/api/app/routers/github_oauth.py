"""GitHub App browser-auth flow + repo linking for the Code Agent."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ALGORITHM, get_current_project, get_current_user
from app.config import settings
from app.db import get_db
from app.models.github import GithubInstallation
from app.models.project import Project
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


# ── State token (signed, short-lived) ────────────────────────────


def _issue_state(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "kind": "github_oauth_state",
        "nonce": secrets.token_hex(8),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=_STATE_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.api_secret_key, algorithm=ALGORITHM)


def _verify_state(state: str, expected_user_id: str) -> None:
    try:
        payload = jwt.decode(state, settings.api_secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid OAuth state: {exc}") from exc
    if payload.get("kind") != "github_oauth_state":
        raise HTTPException(status_code=400, detail="Invalid OAuth state kind")
    if str(payload.get("sub")) != str(expected_user_id):
        raise HTTPException(status_code=400, detail="OAuth state does not match user")


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/status", response_model=StatusResponse)
async def github_status() -> StatusResponse:
    """Public-ish: tells the frontend whether to show the GitHub UI at all."""
    if not github_app.is_enabled():
        return StatusResponse(enabled=False)
    try:
        install_url = github_app.install_url()
    except github_app.GithubAppDisabledError:
        install_url = None
    return StatusResponse(
        enabled=True,
        app_name=settings.github_app_name or None,
        install_url=install_url,
    )


@router.post("/auth-url", response_model=AuthUrlResponse)
async def github_auth_url(
    body: AuthUrlRequest,
    user: User = Depends(get_current_user),
) -> AuthUrlResponse:
    """Return the GitHub authorize URL the frontend should redirect the user to."""
    if not github_app.is_enabled():
        raise HTTPException(status_code=503, detail="GitHub App not configured")
    state = _issue_state(str(user.id))
    url = github_app.authorize_url(state=state, redirect_uri=body.redirect_uri)
    return AuthUrlResponse(url=url)


@router.post("/callback", response_model=CallbackResponse)
async def github_callback(
    body: CallbackRequest,
    user: User = Depends(get_current_user),
) -> CallbackResponse:
    """Finish the browser flow: exchange the code, list installations.

    The user OAuth token is used once here and discarded; everything else uses
    short-lived installation tokens.
    """
    if not github_app.is_enabled():
        raise HTTPException(status_code=503, detail="GitHub App not configured")
    _verify_state(body.state, expected_user_id=str(user.id))
    try:
        user_token = await github_app.exchange_code_for_user_token(body.code)
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
    _user: User = Depends(get_current_user),
) -> list[RepoListItem]:
    if not github_app.is_enabled():
        raise HTTPException(status_code=503, detail="GitHub App not configured")
    try:
        repos = await github_app.list_installation_repos(installation_id)
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
    if not github_app.is_enabled():
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
