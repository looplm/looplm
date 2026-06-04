"""Ingest-key management — UI-facing (JWT + project), gated to observe/traces.

Keys authorize SDK/machine clients to push traces into a first-party
(``looplm``) integration. The plaintext is shown exactly once on creation;
thereafter only a display prefix is returned.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_ingest_key, get_current_project, require_write
from app.db import get_db
from app.models.integrations import IngestKey, Integration, IntegrationType
from app.models.project import Project
from app.schemas.integrations import (
    IngestKeyCreate,
    IngestKeyCreateResponse,
    IngestKeyListResponse,
    IngestKeyResponse,
)

router = APIRouter(prefix="/api/integrations", tags=["ingest-keys"])


async def _get_looplm_integration(
    integration_id: UUID, project: Project, db: AsyncSession
) -> Integration:
    result = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.project_id == project.id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Integration not found"}},
        )
    if integration.type != IntegrationType.looplm:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_TYPE",
                    "message": "Ingest keys are only available for LoopLM tracing integrations",
                }
            },
        )
    return integration


@router.post(
    "/{integration_id}/ingest-keys",
    response_model=IngestKeyCreateResponse,
    status_code=201,
    dependencies=[require_write("observe", "traces")],
)
async def create_ingest_key(
    integration_id: UUID,
    body: IngestKeyCreate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    integration = await _get_looplm_integration(integration_id, project, db)

    plaintext, key_hash, key_prefix = generate_ingest_key()
    key = IngestKey(
        integration_id=integration.id,
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
    )
    db.add(key)
    await db.flush()
    await db.refresh(key)
    return IngestKeyCreateResponse(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
        created_at=key.created_at,
        key=plaintext,
    )


@router.get(
    "/{integration_id}/ingest-keys",
    response_model=IngestKeyListResponse,
    dependencies=[require_write("observe", "traces")],
)
async def list_ingest_keys(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    integration = await _get_looplm_integration(integration_id, project, db)
    result = await db.execute(
        select(IngestKey)
        .where(IngestKey.integration_id == integration.id)
        .order_by(IngestKey.created_at.desc())
    )
    return IngestKeyListResponse(
        data=[IngestKeyResponse.model_validate(k) for k in result.scalars().all()]
    )


@router.delete(
    "/{integration_id}/ingest-keys/{key_id}",
    status_code=204,
    dependencies=[require_write("observe", "traces")],
)
async def revoke_ingest_key(
    integration_id: UUID,
    key_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    integration = await _get_looplm_integration(integration_id, project, db)
    result = await db.execute(
        select(IngestKey).where(
            IngestKey.id == key_id,
            IngestKey.integration_id == integration.id,
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Ingest key not found"}},
        )
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        await db.flush()
    return None
