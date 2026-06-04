"""Resolve the local filesystem path of a project's connected code repository.

Shared by the Code Agent and the repo-aware Architecture Advisor. The rule is:
an explicit `code_agent_repo_path` project setting wins; otherwise materialize the
project's linked GitHub repo (if any) into a managed clone via `github_app`.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.github import GithubInstallation
from app.models.project import Project
from app.services import github_app


class RepoPathError(ValueError):
    """Raised when an explicitly-configured repo path is invalid."""


async def resolve_project_repo(project: Project, db: AsyncSession) -> str | None:
    """Return a local repo path for the project, or None if no repo is connected.

    Raises:
        RepoPathError: an explicit `code_agent_repo_path` setting points nowhere.
        github_app.GithubAppDisabledError / github_app.GithubAppError: clone failed.
    """
    ps = dict(project.settings or {})
    repo_path = ps.get("code_agent_repo_path")
    if repo_path:
        p = Path(repo_path)
        if not p.exists() or not p.is_dir():
            raise RepoPathError(
                f"Repository path does not exist or is not a directory: {repo_path}"
            )
        return repo_path

    installation = (
        await db.execute(
            select(GithubInstallation).where(GithubInstallation.project_id == project.id)
        )
    ).scalar_one_or_none()
    if installation and installation.repo_full_name:
        creds = await github_app.resolve_creds(db, project.id)
        if not github_app.is_enabled(creds):
            raise github_app.GithubAppDisabledError(
                "GitHub App is not configured for this project."
            )
        cloned = await github_app.ensure_repo_clone(
            creds,
            project_id=project.id,
            installation_id=installation.installation_id,
            repo_full_name=installation.repo_full_name,
            default_branch=installation.repo_branch or installation.repo_default_branch,
        )
        return str(cloned)

    return None
