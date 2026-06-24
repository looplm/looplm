"""Chunk relevance labeling endpoints — the human-in-the-loop retrieval judging flow.

A human opens an eval run, sees the chunks each case retrieved, and marks them relevant or
not. Those labels (pooled across runs per test case) become the ground truth the
chunk-level retrieval metrics are computed against.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section, require_write
from app.db import get_db
from app.models.chunk_labels import ChunkRelevanceLabel, TestCaseLabelingStatus
from app.models.evaluations import EvalResult, EvalRun
from app.models.project import Project
from app.models.user import User
from app.schemas.retrieval import (
    ChunkLabelBatch,
    LabelingRunResponse,
    LabelingStatusUpdate,
)
from app.services.chunk_labeling import build_labeling_view


def _display_name(email: str | None) -> str | None:
    """Compact display name for a labeler — the local part of their email."""
    if not email:
        return None
    return email.split("@", 1)[0]

router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline"],
    dependencies=[require_section("evaluate", "labeling")],
)


async def _latest_or_named_run(
    db: AsyncSession, project: Project, run_id: UUID | None
) -> EvalRun:
    run_filter = [EvalRun.project_id == project.id]
    if run_id is not None:
        run_filter.append(EvalRun.id == run_id)
    run = (
        await db.execute(
            select(EvalRun).where(*run_filter).order_by(EvalRun.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Eval run not found"}},
        )
    return run


@router.get("/labeling", response_model=LabelingRunResponse)
async def get_labeling_view(
    run_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Retrieved chunks for a run, grouped by case, with any existing labels merged in."""
    run = await _latest_or_named_run(db, project, run_id)
    results = (
        await db.execute(select(EvalResult).where(EvalResult.run_id == run.id))
    ).scalars().all()

    labels = (
        await db.execute(
            select(ChunkRelevanceLabel).where(ChunkRelevanceLabel.project_id == project.id)
        )
    ).scalars().all()
    labels_by_key = {(lbl.test_id, lbl.chunk_id): lbl.relevant for lbl in labels}

    # Resolve labeler ids to display names in one query.
    labeler_ids = {lbl.labeled_by for lbl in labels if lbl.labeled_by}
    names: dict = {}
    if labeler_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(labeler_ids)))
        ).scalars().all()
        names = {u.id: _display_name(u.email) for u in users}
    labeler_by_key = {
        (lbl.test_id, lbl.chunk_id): names.get(lbl.labeled_by)
        for lbl in labels
        if lbl.labeled_by and names.get(lbl.labeled_by)
    }

    statuses = (
        await db.execute(
            select(TestCaseLabelingStatus).where(TestCaseLabelingStatus.project_id == project.id)
        )
    ).scalars().all()
    complete_by_test = {s.test_id: s.complete for s in statuses}

    return build_labeling_view(
        run,
        results,
        labels_by_key,
        labeler_by_key=labeler_by_key,
        complete_by_test=complete_by_test,
    )


@router.put(
    "/labeling/status",
    dependencies=[require_write("evaluate", "labeling")],
)
async def set_labeling_status(
    body: LabelingStatusUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Manually mark a test case's chunk labeling as complete or not."""
    status = (
        await db.execute(
            select(TestCaseLabelingStatus).where(
                TestCaseLabelingStatus.project_id == project.id,
                TestCaseLabelingStatus.test_id == body.test_id,
            )
        )
    ).scalar_one_or_none()
    if status is None:
        db.add(
            TestCaseLabelingStatus(
                project_id=project.id,
                test_id=body.test_id,
                complete=body.complete,
                marked_by=user.id,
            )
        )
    else:
        status.complete = body.complete
        status.marked_by = user.id
    await db.flush()
    return {"test_id": body.test_id, "complete": body.complete}


@router.post(
    "/labels",
    dependencies=[require_write("evaluate", "labeling")],
)
async def upsert_labels(
    body: ChunkLabelBatch,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Create or update relevance labels for (test_id, chunk_id) pairs in this project."""
    existing = (
        await db.execute(
            select(ChunkRelevanceLabel).where(ChunkRelevanceLabel.project_id == project.id)
        )
    ).scalars().all()
    by_key = {(lbl.test_id, lbl.chunk_id): lbl for lbl in existing}

    saved = 0
    for item in body.labels:
        current = by_key.get((item.test_id, item.chunk_id))
        if current is None:
            db.add(
                ChunkRelevanceLabel(
                    project_id=project.id,
                    test_id=item.test_id,
                    chunk_id=item.chunk_id,
                    relevant=item.relevant,
                    content_preview=item.content_preview,
                    url=item.url,
                    title=item.title,
                    labeled_by=user.id,
                )
            )
        else:
            current.relevant = item.relevant
            current.labeled_by = user.id
            if item.content_preview is not None:
                current.content_preview = item.content_preview
            if item.url is not None:
                current.url = item.url
            if item.title is not None:
                current.title = item.title
        saved += 1

    await db.flush()
    return {"saved": saved}
