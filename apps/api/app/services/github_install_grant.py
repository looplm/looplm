"""Short-lived grants binding a GitHub App installation to a project and user.

`fetch_installation_token` will mint a token for *any* installation id of the App, and the App
credentials are often the instance-wide env App shared by every project. So an installation id
arriving in a URL is not evidence of anything: without this check, a member of one project can
enumerate small integer ids and read another tenant's private repositories.

An installation is usable by a project when either

* it is already linked to that project (a `GithubInstallation` row), or
* the caller holds a grant issued by ``/callback`` after the user completed the GitHub browser
  flow, which is the only moment we know the acting user actually controls the installation.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ALGORITHM
from app.config import settings
from app.models.github import GithubInstallation
from app.models.project import Project
from app.models.user import User

_GRANT_TTL_SECONDS = 600  # the user has to finish picking a repo within this
_GRANT_KIND = "github_install_grant"


def issue_grant(user_id: UUID, project_id: UUID, installation_ids: list[int]) -> str:
    """Sign the set of installations this user just proved control of."""
    payload = {
        "sub": str(user_id),
        "pid": str(project_id),
        "ids": [int(i) for i in installation_ids],
        "kind": _GRANT_KIND,
        "nonce": secrets.token_hex(8),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=_GRANT_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.api_secret_key, algorithm=ALGORITHM)


def _grant_allows(grant: str, user_id: UUID, project_id: UUID, installation_id: int) -> bool:
    try:
        payload = jwt.decode(grant, settings.api_secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return False
    if payload.get("kind") != _GRANT_KIND:
        return False
    if str(payload.get("sub")) != str(user_id) or str(payload.get("pid")) != str(project_id):
        return False
    ids = payload.get("ids")
    return isinstance(ids, list) and installation_id in ids


async def assert_installation_allowed(
    db: AsyncSession,
    project: Project,
    user: User,
    installation_id: int,
    grant: str | None = None,
) -> None:
    """Raise 403 unless *installation_id* is usable by *project*."""
    linked = (
        await db.execute(
            select(GithubInstallation.id).where(
                GithubInstallation.project_id == project.id,
                GithubInstallation.installation_id == installation_id,
            )
        )
    ).scalar_one_or_none()
    if linked is not None:
        return
    if grant and _grant_allows(grant, user.id, project.id, installation_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "This GitHub installation is not available for this project. "
            "Reconnect GitHub to pick an installation you control."
        ),
    )
