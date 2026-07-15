"""Passage document-offset backfill endpoints (labeling maintenance).

A background job that anchors NULL-offset passage selections to document coordinates once their
chunk's index doc carries ``chunk_char_start``. Launch is write-gated on the labeling page and
scoped to the current project; the worker owns its own session (see ``backfill_worker``). The UI
polls ``/passage-offset-backfill/latest`` for status + per-outcome tallies.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_write
from app.db import async_session, get_db
from app.models.passage_offset_backfill import PassageOffsetBackfillRun
from app.models.project import Project
from app.routers.chunk_labels.backfill_worker import run_passage_offset_backfill
from app.schemas.retrieval import (
    PassageOffsetBackfillLatest,
    PassageOffsetBackfillRunResponse,
)

router = APIRouter()

# Keep background tasks referenced so they aren't garbage-collected mid-run.
_tasks: dict[UUID, asyncio.Task] = {}


async def _latest_run(
    db: AsyncSession, project_id: UUID
) -> PassageOffsetBackfillRun | None:
    return (
        await db.execute(
            select(PassageOffsetBackfillRun)
            .where(PassageOffsetBackfillRun.project_id == project_id)
            .order_by(PassageOffsetBackfillRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@router.post(
    "/passage-offset-backfill",
    response_model=PassageOffsetBackfillRunResponse,
    status_code=202,
    dependencies=[require_write("evaluate", "labeling")],
)
async def start_passage_offset_backfill(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Launch a backfill of document offsets for this project's passage labels.

    Refuses (409) if a run is already pending/running so two launches can't race. The work happens
    in a background task; poll ``/passage-offset-backfill/latest`` for progress and tallies.
    """
    latest = await _latest_run(db, project.id)
    if latest is not None and latest.status in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "BACKFILL_IN_PROGRESS",
                    "message": "A passage offset backfill is already running for this project.",
                }
            },
        )

    run = PassageOffsetBackfillRun(project_id=project.id, status="pending")
    db.add(run)
    await db.flush()
    await db.refresh(run)
    run_id = run.id
    project_id = project.id
    # Commit before spawning: the worker opens its own session and must see the row.
    await db.commit()

    task = asyncio.create_task(
        run_passage_offset_backfill(
            run_id=run_id, project_id=project_id, db_factory=async_session
        )
    )
    _tasks[run_id] = task
    task.add_done_callback(lambda _t, rid=run_id: _tasks.pop(rid, None))

    fresh = await _latest_run(db, project_id)
    return PassageOffsetBackfillRunResponse.model_validate(fresh)


@router.get(
    "/passage-offset-backfill/latest",
    response_model=PassageOffsetBackfillLatest,
)
async def get_latest_passage_offset_backfill(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """The project's most recent backfill run (for the trigger button's status), or None."""
    latest = await _latest_run(db, project.id)
    return PassageOffsetBackfillLatest(
        run=PassageOffsetBackfillRunResponse.model_validate(latest) if latest else None
    )
