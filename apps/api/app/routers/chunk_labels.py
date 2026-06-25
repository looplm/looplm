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
from app.index_providers.registry import build_index_provider
from app.models.chunk_labels import (
    SLICE_VALUES,
    ChunkRelevanceLabel,
    TestCaseLabelingStatus,
)
from app.models.evaluations import EvalResult, EvalRun
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.models.user import User
from app.schemas.retrieval import (
    ChunkLabelBatch,
    ChunkMetadataResponse,
    LabelingPoolResponse,
    LabelingRunResponse,
    LabelingSliceUpdate,
    LabelingStatusUpdate,
)
from app.services.chunk_labeling import build_labeling_view, build_pool_view
from app.services.chunk_pool import DEFAULT_POOL_DEPTH, SLICE_POOL_DEPTH, assemble_pool


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


async def _project_labels(
    db: AsyncSession, project: Project
) -> tuple[dict[tuple[str, str], bool], dict[tuple[str, str], str]]:
    """Load the project's chunk labels as ``(test_id, chunk_id) ->`` relevant / labeler name.

    Labels are pooled across runs, so a judgment made in any run shows up wherever that
    ``(test_id, chunk_id)`` pair appears. Labeler ids are resolved to display names in one query.
    """
    labels = (
        await db.execute(
            select(ChunkRelevanceLabel).where(ChunkRelevanceLabel.project_id == project.id)
        )
    ).scalars().all()
    labels_by_key = {(lbl.test_id, lbl.chunk_id): lbl.relevant for lbl in labels}

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
    return labels_by_key, labeler_by_key


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

    labels_by_key, labeler_by_key = await _project_labels(db, project)

    statuses = (
        await db.execute(
            select(TestCaseLabelingStatus).where(TestCaseLabelingStatus.project_id == project.id)
        )
    ).scalars().all()
    complete_by_test = {s.test_id: s.complete for s in statuses}
    slice_by_test = {s.test_id: s.slice for s in statuses if s.slice}

    return build_labeling_view(
        run,
        results,
        labels_by_key,
        labeler_by_key=labeler_by_key,
        complete_by_test=complete_by_test,
        slice_by_test=slice_by_test,
    )


# Hard cap on per-head pool depth so a "load deeper pool" request can't hammer the index.
_MAX_POOL_DEPTH = 50


@router.get("/labeling/pool", response_model=LabelingPoolResponse)
async def get_labeling_pool(
    test_id: str,
    run_id: UUID | None = None,
    q: str | None = None,
    depth: int | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Multi-head candidate pool for one test case: trace captures ∪ index search heads.

    Unions the chunks the case retrieved with fresh candidates from the connected index
    (keyword/vector/hybrid), deduped by chunk id, so a labeler can judge relevant chunks the
    system *missed* — the only way pooled recall can exceed what the system already found.
    ``q`` overrides the search query (the A3 manual "find more candidates" box); without it the
    case's own input is used and the trace chunks seed the pool. ``depth`` tunes per-head top-k.
    Falls back to a trace-only pool when no index provider is connected.
    """
    run = await _latest_or_named_run(db, project, run_id)
    result = (
        await db.execute(
            select(EvalResult)
            .where(EvalResult.run_id == run.id, EvalResult.test_id == test_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Test case not found in run"}},
        )

    # A manual-search query stands on its own; the case input seeds with its trace chunks.
    manual = bool(q and q.strip())
    query = (q if manual else str(result.input or "")).strip()
    meta = result.result_metadata if isinstance(result.result_metadata, dict) else {}
    raw_chunks = meta.get("retrieved_chunks")
    trace_chunks = [] if manual else (raw_chunks if isinstance(raw_chunks, list) else [])

    # Explicit depth wins; otherwise pool deeper on risk slices where a deep-rank miss matters.
    if depth:
        per_head = max(1, min(depth, _MAX_POOL_DEPTH))
    else:
        status = (
            await db.execute(
                select(TestCaseLabelingStatus.slice).where(
                    TestCaseLabelingStatus.project_id == project.id,
                    TestCaseLabelingStatus.test_id == test_id,
                )
            )
        ).scalar_one_or_none()
        per_head = SLICE_POOL_DEPTH.get(status or "", DEFAULT_POOL_DEPTH)

    provider_row = (
        await db.execute(
            select(IndexProvider)
            .where(IndexProvider.project_id == project.id)
            .order_by(IndexProvider.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    provider = build_index_provider(provider_row) if provider_row is not None else None
    try:
        pool = await assemble_pool(
            provider, query, trace_chunks=trace_chunks, per_head_depth=per_head
        )
    finally:
        if provider is not None:
            await provider.aclose()

    labels_by_key, labeler_by_key = await _project_labels(db, project)
    return build_pool_view(
        test_id,
        str(result.input or "") or None,
        pool,
        provider_connected=provider_row is not None,
        labels_by_key=labels_by_key,
        labeler_by_key=labeler_by_key,
    )


@router.get("/chunk-metadata", response_model=ChunkMetadataResponse)
async def get_chunk_metadata(
    chunk_id: str,
    provider_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """All index fields for a chunk, fetched live from the project's index provider.

    Returns ``provider_connected=False`` when the project has no index provider, so the UI
    can hide the feature; ``available=False`` when the chunk is not found in the index.
    """
    pf = [IndexProvider.project_id == project.id]
    if provider_id is not None:
        pf.append(IndexProvider.id == provider_id)
    provider_row = (
        await db.execute(
            select(IndexProvider).where(*pf).order_by(IndexProvider.created_at.asc()).limit(1)
        )
    ).scalar_one_or_none()
    if provider_row is None:
        return ChunkMetadataResponse(provider_connected=False, available=False)

    provider = build_index_provider(provider_row)
    try:
        docs = await provider.fetch_documents_by_key([chunk_id])
    finally:
        await provider.aclose()

    fields = docs.get(chunk_id)
    return ChunkMetadataResponse(
        provider_connected=True, available=fields is not None, fields=fields
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


@router.put(
    "/labeling/slice",
    dependencies=[require_write("evaluate", "labeling")],
)
async def set_labeling_slice(
    body: LabelingSliceUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Assign a test case to a risk slice (broad | safety | adversarial), or clear it."""
    new_slice = body.slice or None
    if new_slice is not None and new_slice not in SLICE_VALUES:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "INVALID_SLICE", "message": f"slice must be one of {SLICE_VALUES}"}},
        )
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
                complete=False,
                slice=new_slice,
                marked_by=user.id,
            )
        )
    else:
        status.slice = new_slice
        status.marked_by = user.id
    await db.flush()
    return {"test_id": body.test_id, "slice": new_slice}


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
