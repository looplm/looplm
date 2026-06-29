"""Shared helpers and module state for the prompts router package."""

import asyncio
import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.github import GithubInstallation
from app.models.project import Project
from app.models.prompts import PromptExtraction
from app.schemas.prompts import (
    PlannedLocation,
    PromptExtractionResponse,
    PromptOut,
)
from app.services import github_app
from app.services.repo_resolver import RepoPathError, resolve_project_repo

logger = logging.getLogger(__name__)

_SUPPORTED_PROVIDERS = {"openai", "anthropic", "azure_openai"}

# Single shared registry of in-flight extraction tasks, keyed by extraction id.
# Both sub-routers must import and mutate this same instance.
_extraction_tasks: dict[UUID, asyncio.Task] = {}


def _code_agent_params(project: Project) -> dict:
    """Resolve the Code Agent provider/model/credentials from project settings.

    Shared by GitHub extraction and per-prompt recheck — both read the repo with
    the same agent infra. Unsupported provider values fall back to 'anthropic',
    matching the Settings UI.
    """
    ps = dict(project.settings or {})
    stored = ps.get("code_agent_provider", "anthropic")
    provider = stored if stored in _SUPPORTED_PROVIDERS else "anthropic"
    if provider != stored:
        logger.warning(
            "Project %s has unsupported code_agent_provider %r; falling back to 'anthropic'",
            project.id, stored,
        )
    return {
        "provider": provider,
        "model": ps.get("code_agent_model"),
        "api_key": ps.get("code_agent_api_key"),
        "azure_endpoint": ps.get("code_agent_azure_endpoint"),
        "azure_api_version": ps.get("code_agent_azure_api_version"),
    }


def _extraction_to_out(e: PromptExtraction) -> PromptExtractionResponse:
    return PromptExtractionResponse(
        id=str(e.id),
        status=e.status,
        error=e.error,
        summary=e.summary,
        files_analyzed=e.files_analyzed or [],
        extracted_count=e.extracted_count or 0,
        total_cost_usd=e.total_cost_usd,
        num_turns=e.num_turns,
        progress_message=e.progress_message,
        progress_log=e.progress_log or [],
        planned_locations=[PlannedLocation(**loc) for loc in (e.planned_locations or [])],
        started_at=e.started_at,
        completed_at=e.completed_at,
    )


def _prompt_to_out(p) -> PromptOut:
    return PromptOut(
        id=str(p.id),
        integration_id=str(p.integration_id),
        external_id=p.external_id,
        name=p.name,
        template=p.template,
        version=p.version,
        variables=p.variables or [],
        metadata=p.prompt_metadata or {},
        source=p.integration.type.value if p.integration else "",
        cluster_path=p.cluster_path or [],
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


async def _resolve_repo_or_400(project: Project, db: AsyncSession) -> tuple[str, str | None]:
    """Resolve the local repo path + repo_full_name, raising HTTP errors as the
    extraction endpoints expect."""
    try:
        repo_path = await resolve_project_repo(project, db)
    except RepoPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (github_app.GithubAppDisabledError, github_app.GithubAppError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not repo_path:
        raise HTTPException(
            status_code=400,
            detail="No code repository is connected for this project. Connect one in Settings → GitHub.",
        )
    installation = (
        await db.execute(
            select(GithubInstallation).where(GithubInstallation.project_id == project.id)
        )
    ).scalar_one_or_none()
    return repo_path, (installation.repo_full_name if installation else None)
