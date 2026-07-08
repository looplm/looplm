"""Project CRUD endpoints."""

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_platform_admin
from app.db import get_db
from app.models.project import Project
from app.models.project_member import ALL_SECTIONS, ProjectMember
from app.models.user import User
from app.schemas.projects import (
    EmbeddingTestResult,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
    RetrievalSourceDetection,
    TransferOwnership,
)
from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService, merge_llm_settings
from app.services.llm_usage_tracker import record_llm_usage
from app.services.retrieval_readiness import probe_embedding_status
from app.services.retrieval_detection import detect_retrieval_source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

# Settings keys that contain secrets — mask on read, skip no-op updates on write.
_SECRET_SETTINGS_KEYS = {
    "code_agent_api_key",
    "openai_api_key",
    "azure_openai_api_key",
    "agent_retrieval_token",
}


def _mask(value: str | None) -> str:
    """Mask a secret: show first 4 + last 3 chars."""
    if not value:
        return ""
    if len(value) <= 7:
        return value[0] + "..." + value[-1] if len(value) >= 2 else "***"
    return value[:4] + "..." + value[-3:]


def _mask_settings(settings: dict) -> dict:
    """Return a copy of settings with secret values masked."""
    out = dict(settings or {})
    for key in _SECRET_SETTINGS_KEYS:
        if key in out and out[key]:
            out[key] = _mask(out[key])
    return out


def _project_response(project: Project, role: str = "owner") -> ProjectResponse:
    """Build a ProjectResponse with masked settings."""
    return ProjectResponse(
        id=project.id,
        owner_id=project.owner_id,
        name=project.name,
        description=project.description,
        settings=_mask_settings(project.settings or {}),
        created_at=project.created_at,
        updated_at=project.updated_at,
        role=role,
    )


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    # Owned projects
    result = await db.execute(
        select(Project).where(Project.owner_id == _user.id).order_by(Project.created_at.asc())
    )
    projects = [_project_response(p, role="owner") for p in result.scalars().all()]

    # Projects where the user is a member
    result = await db.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == _user.id)
        .order_by(Project.created_at.asc())
    )
    for p, member_role in result.all():
        projects.append(_project_response(p, role=member_role))

    return ProjectListResponse(data=projects)


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_platform_admin),
):
    """Create a new project. Restricted to platform admins — regular users join
    existing projects by invitation only."""
    project = Project(
        owner_id=_user.id,
        name=body.name,
        description=body.description,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return _project_response(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == _user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_response(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == _user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.settings is not None:
        merged = dict(project.settings or {})
        for key, value in body.settings.items():
            # Skip secret keys sent back with their masked value (no-op update)
            if key in _SECRET_SETTINGS_KEYS and value and "..." in str(value):
                continue
            merged[key] = value
        project.settings = merged
    project.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(project)
    return _project_response(project)


@router.post(
    "/{project_id}/detect-retrieval-source", response_model=RetrievalSourceDetection
)
async def detect_retrieval_source_endpoint(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> RetrievalSourceDetection:
    """Use LLM reasoning to pick the project's retrieval-context source.

    Owner-only. Samples recent traces, asks the analysis LLM which payload key or
    span carries the retrieved RAG context, and returns the suggestion plus the
    candidates considered. Does not persist — the client saves the accepted
    source via PATCH ``settings.retrieval_source``.
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == _user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        llm = AnalysisLlmService(
            user_settings=_user.settings, project_settings=project.settings
        )
    except AnalysisLlmConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = await detect_retrieval_source(db, project, llm)
    except Exception as exc:
        logger.exception("Retrieval-source detection failed")
        raise HTTPException(status_code=502, detail="Retrieval-source detection failed") from exc

    usage = result.get("usage")
    if usage is not None:
        await record_llm_usage(
            db,
            project_id=project.id,
            service_name="retrieval_detection",
            function_name="detect_retrieval_source",
            provider=llm.provider,
            model=llm.model,
            usage=usage,
        )
        await db.commit()

    return RetrievalSourceDetection(
        suggestion=result.get("suggestion"),
        candidates=result.get("candidates", {"payload_keys": [], "spans": []}),
    )


@router.post("/{project_id}/test-embedding", response_model=EmbeddingTestResult)
async def test_embedding(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> EmbeddingTestResult:
    """Embed a tiny probe string with the project's saved embedding config.

    Owner-only. Confirms the embedding deployment/model + credentials actually work and reports
    the vector dimensions returned (so the user can verify they match their index's vector field).
    Save settings before testing — this reads the persisted project settings.
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == _user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return await probe_embedding_status(merge_llm_settings(project.settings, _user.settings))


@router.post("/{project_id}/transfer-ownership", response_model=ProjectResponse)
async def transfer_ownership(
    project_id: UUID,
    body: TransferOwnership,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Hand the project over to an existing member.

    Owner-only. The chosen member is promoted out of the members table to become
    the owner, and the previous owner stays on as an admin member so they keep
    full access.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id != _user.id:
        raise HTTPException(
            status_code=403, detail="Only the project owner can transfer ownership"
        )
    if body.new_owner_id == project.owner_id:
        raise HTTPException(status_code=400, detail="That user is already the owner")

    # The new owner must already be a member of this project.
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == body.new_owner_id,
        )
    )
    new_owner_member = result.scalar_one_or_none()
    if not new_owner_member:
        raise HTTPException(
            status_code=400, detail="New owner must be an existing project member"
        )

    previous_owner_id = project.owner_id

    # Promote the new owner out of the members table, demote the previous owner
    # to an admin member (the owner never had a member row — it can't conflict).
    await db.delete(new_owner_member)
    db.add(
        ProjectMember(
            project_id=project_id,
            user_id=previous_owner_id,
            role="admin",
            allowed_sections=list(ALL_SECTIONS),
            allowed_pages=None,
            write_pages=None,
        )
    )
    project.owner_id = body.new_owner_id
    project.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(project)
    return _project_response(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == _user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Prevent deleting the last project
    count_result = await db.execute(
        select(Project.id).where(Project.owner_id == _user.id)
    )
    if len(count_result.all()) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete your only project")

    await db.delete(project)
    return None
