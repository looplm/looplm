"""Chunk relevance labeling endpoints — the human-in-the-loop retrieval judging flow.

A human opens an eval run, sees the chunks each case retrieved, and marks them relevant or
not. Those labels (pooled across runs per test case) become the ground truth the
chunk-level retrieval metrics are computed against.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section, require_write
from app.cache import cache_get_json, cache_set_json
from app.db import get_db
from app.index_providers.registry import build_index_provider
from app.models.chunk_labels import (
    GRADE_MAX,
    GRADE_MIN,
    SLICE_VALUES,
    ChunkGoldLabel,
    ChunkRelevanceLabel,
    TestCaseLabelingStatus,
    is_valid_grade,
)
from app.models.evaluations import EvalResult, EvalRun
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.models.user import User
from app.schemas.retrieval import (
    AgreementReport,
    ChunkLabelBatch,
    ChunkMetadataResponse,
    GoldUpdate,
    LabelingCase,
    LabelingPoolResponse,
    LabelingRunResponse,
    LabelingSliceUpdate,
    LabelingStatusUpdate,
)
from app.services.chunk_agreement import Vote, build_agreement_report
from app.services.chunk_labeling import (
    build_labeling_cases,
    build_pool_view,
    merge_labeling_view,
)
from app.services.chunk_pool import (
    DEFAULT_POOL_DEPTH,
    SLICE_POOL_DEPTH,
    PooledChunk,
    PoolResult,
    assemble_pool,
)


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


# Safety bound on the cached labeling skeleton — freshness is enforced by the fingerprint, so
# this just keeps abandoned project keys from living forever (1 day).
_LABELING_CACHE_TTL = 86_400


def _labeling_cache_key(project_id: UUID) -> str:
    return f"labeling:cases:{project_id}"


async def _results_fingerprint(db: AsyncSession, project: Project) -> str:
    """Cheap content fingerprint of the project's eval results.

    Changes whenever a result is added or removed (new run, streamed result, deleted run), so a
    cached labeling skeleton built under a different fingerprint is recomputed on the next read.
    Counting + max(created_at) avoids loading the (large) ``result_metadata`` JSONB the skeleton
    is built from.
    """
    count, latest = (
        await db.execute(
            select(func.count(EvalResult.id), func.max(EvalResult.created_at))
            .join(EvalRun, EvalResult.run_id == EvalRun.id)
            .where(EvalRun.project_id == project.id)
        )
    ).one()
    return f"{count or 0}:{latest.isoformat() if latest else '0'}"


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
    db: AsyncSession, project: Project, *, user_id: UUID | None = None
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], str], dict[str, list[str]]]:
    """Load chunk labels for the labeling view, scoped to one annotator's own judgments.

    Returns ``(labels_by_key, labeler_by_key, labelers_by_test)``. The first two are scoped to
    ``user_id`` (so each annotator sees and edits their *own* graded relevance verdicts), keyed
    by ``(test_id, chunk_id)`` — ``labels_by_key`` maps to the 0..3 grade. ``labelers_by_test``
    lists every annotator (across all annotators) who has judged any chunk in a test case, for
    the per-case "who labeled" display.
    """
    labels = (
        await db.execute(
            select(ChunkRelevanceLabel).where(ChunkRelevanceLabel.project_id == project.id)
        )
    ).scalars().all()

    labeler_ids = {lbl.labeled_by for lbl in labels if lbl.labeled_by}
    names: dict = {}
    if labeler_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(labeler_ids)))
        ).scalars().all()
        names = {u.id: _display_name(u.email) for u in users}

    scoped = [lbl for lbl in labels if user_id is None or lbl.labeled_by == user_id]
    labels_by_key = {(lbl.test_id, lbl.chunk_id): lbl.relevance for lbl in scoped}
    labeler_by_key = {
        (lbl.test_id, lbl.chunk_id): names.get(lbl.labeled_by)
        for lbl in scoped
        if lbl.labeled_by and names.get(lbl.labeled_by)
    }

    labelers_by_test: dict[str, list[str]] = {}
    for lbl in labels:
        name = names.get(lbl.labeled_by)
        if name and name not in labelers_by_test.setdefault(lbl.test_id, []):
            labelers_by_test[lbl.test_id].append(name)
    return labels_by_key, labeler_by_key, labelers_by_test


@router.get("/labeling", response_model=LabelingRunResponse)
async def get_labeling_view(
    run_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Retrieved chunks grouped by test case, with the viewer's own labels merged in.

    Labels are pooled per query across runs, so labeling isn't tied to a single run: by default
    this aggregates every test case the project's eval runs captured, deduped by ``test_id`` with
    the most recent run's capture winning. Passing ``run_id`` scopes the view to one run instead.

    The expensive part — reading every result's ``retrieved_chunks`` JSON into the per-case
    skeleton — is cached in Redis per project (default, all-runs path), keyed against a cheap
    result fingerprint so new/removed results recompute it immediately. The viewer's own labels
    and per-case status are small and always re-merged live, so judgments are never stale.
    """
    # Per-case skeleton (no labels) + total case count, from cache when possible.
    if run_id is not None:
        run = await _latest_or_named_run(db, project, run_id)
        results = (
            await db.execute(select(EvalResult).where(EvalResult.run_id == run.id))
        ).scalars().all()
        cases, total_cases = build_labeling_cases(results)
        view_run_id: str | None = str(run_id)
        view_run_name: str | None = run.name
    else:
        view_run_id = view_run_name = None
        cache_key = _labeling_cache_key(project.id)
        fingerprint = await _results_fingerprint(db, project)
        cached = await cache_get_json(cache_key)
        if cached and cached.get("fingerprint") == fingerprint:
            cases = [LabelingCase.model_validate(c) for c in cached["cases"]]
            total_cases = cached["total_cases"]
        else:
            # All results across the project's runs, newest run first so the latest capture of a
            # query wins when build_labeling_cases dedupes by test_id.
            results = (
                await db.execute(
                    select(EvalResult)
                    .join(EvalRun, EvalResult.run_id == EvalRun.id)
                    .where(EvalRun.project_id == project.id)
                    .order_by(EvalRun.created_at.desc())
                )
            ).scalars().all()
            cases, total_cases = build_labeling_cases(results)
            await cache_set_json(
                cache_key,
                {
                    "fingerprint": fingerprint,
                    "total_cases": total_cases,
                    "cases": [c.model_dump() for c in cases],
                },
                ttl_seconds=_LABELING_CACHE_TTL,
            )

    labels_by_key, labeler_by_key, labelers_by_test = await _project_labels(
        db, project, user_id=user.id
    )

    statuses = (
        await db.execute(
            select(TestCaseLabelingStatus).where(TestCaseLabelingStatus.project_id == project.id)
        )
    ).scalars().all()
    complete_by_test = {s.test_id: s.complete for s in statuses}
    slice_by_test = {s.test_id: s.slice for s in statuses if s.slice}

    return merge_labeling_view(
        cases,
        total_cases,
        labels_by_key,
        run_id=view_run_id,
        run_name=view_run_name,
        labeler_by_key=labeler_by_key,
        complete_by_test=complete_by_test,
        slice_by_test=slice_by_test,
        labelers_by_test=labelers_by_test,
    )


# Hard cap on per-head pool depth so a "load deeper pool" request can't hammer the index.
_MAX_POOL_DEPTH = 50

# The auto-pool (a case's own input against the index heads) is user-independent and stable
# until the index is re-indexed, so we cache the assembled pool in Redis. This is what lets the
# labeling view eager-load per-method ranks for every case without re-hitting Azure on every
# page open — mirroring the reference design, which persists the pool on first visit. Manual
# searches (an explicit ``q``) always run fresh and are never cached. TTL is a freshness bound;
# changing a case's slice changes its depth, which changes the key, so it re-pools immediately.
_POOL_CACHE_TTL = 21_600  # 6 hours


def _pool_cache_key(project_id: UUID, test_id: str, per_head: int) -> str:
    return f"labeling:pool:{project_id}:{test_id}:{per_head}"


def _serialize_pool(pool: PoolResult, computed_at: str) -> dict:
    return {
        "computed_at": computed_at,
        "heads_ran": pool.heads_ran,
        "heads_failed": pool.heads_failed,
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "title": c.title,
                "url": c.url,
                "content_preview": c.content_preview,
                "score": c.score,
                "provenance": c.provenance,
                "ranks": c.ranks,
            }
            for c in pool.chunks
        ],
    }


def _deserialize_pool(data: dict) -> PoolResult:
    return PoolResult(
        chunks=[
            PooledChunk(
                chunk_id=c["chunk_id"],
                title=c.get("title"),
                url=c.get("url"),
                content_preview=c.get("content_preview"),
                score=c.get("score"),
                provenance=list(c.get("provenance") or []),
                ranks={k: int(v) for k, v in (c.get("ranks") or {}).items()},
            )
            for c in data.get("chunks", [])
        ],
        heads_ran=list(data.get("heads_ran") or []),
        heads_failed=dict(data.get("heads_failed") or {}),
    )


@router.get("/labeling/pool", response_model=LabelingPoolResponse)
async def get_labeling_pool(
    test_id: str,
    run_id: UUID | None = None,
    q: str | None = None,
    depth: int | None = None,
    refresh: bool = False,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Multi-head candidate pool for one test case: trace captures ∪ index search heads.

    Unions the chunks the case retrieved with fresh candidates from the connected index
    (keyword/vector/hybrid), deduped by chunk id, so a labeler can judge relevant chunks the
    system *missed* — the only way pooled recall can exceed what the system already found.
    ``q`` overrides the search query (the A3 manual "find more candidates" box); without it the
    case's own input is used and the trace chunks seed the pool. ``depth`` tunes per-head top-k.
    Falls back to a trace-only pool when no index provider is connected.
    """
    if run_id is not None:
        run = await _latest_or_named_run(db, project, run_id)
        result = (
            await db.execute(
                select(EvalResult)
                .where(EvalResult.run_id == run.id, EvalResult.test_id == test_id)
                .limit(1)
            )
        ).scalar_one_or_none()
    else:
        # No run pinned: take the most recent capture of this test case across all runs.
        result = (
            await db.execute(
                select(EvalResult)
                .join(EvalRun, EvalResult.run_id == EvalRun.id)
                .where(EvalRun.project_id == project.id, EvalResult.test_id == test_id)
                .order_by(EvalRun.created_at.desc())
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

    # The auto-pool is user-independent and stable until re-index, so serve it from Redis when
    # cached. ``refresh`` forces a recompute (the explicit "recompute pooling" button); a manual
    # search query stands alone and is always run fresh.
    cache_key = None if manual else _pool_cache_key(project.id, test_id, per_head)
    pool: PoolResult | None = None
    computed_at: str | None = None
    if cache_key and not refresh:
        cached = await cache_get_json(cache_key)
        if cached is not None:
            pool = _deserialize_pool(cached)
            computed_at = cached.get("computed_at")

    if pool is None:
        provider = build_index_provider(provider_row) if provider_row is not None else None
        try:
            pool = await assemble_pool(
                provider, query, trace_chunks=trace_chunks, per_head_depth=per_head
            )
        finally:
            if provider is not None:
                await provider.aclose()
        computed_at = datetime.now(timezone.utc).isoformat()
        if cache_key:
            await cache_set_json(
                cache_key, _serialize_pool(pool, computed_at), ttl_seconds=_POOL_CACHE_TTL
            )

    labels_by_key, labeler_by_key, _ = await _project_labels(db, project, user_id=user.id)
    return build_pool_view(
        test_id,
        str(result.input or "") or None,
        pool,
        provider_connected=provider_row is not None,
        labels_by_key=labels_by_key,
        labeler_by_key=labeler_by_key,
        computed_at=computed_at,
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
    """Create or update the current user's graded relevance labels for (test_id, chunk_id) pairs.

    Labels are per-annotator: each user owns their own row for a chunk, so two annotators can
    disagree (the rows inter-annotator agreement and gold resolution are built from). Saving
    only ever touches the calling user's own label. ``relevance`` is the graded 0..3 score.
    """
    for item in body.labels:
        if not is_valid_grade(item.relevance):
            raise HTTPException(
                status_code=422,
                detail={
                    "error": {
                        "code": "INVALID_GRADE",
                        "message": f"relevance must be an integer {GRADE_MIN}..{GRADE_MAX}",
                    }
                },
            )

    existing = (
        await db.execute(
            select(ChunkRelevanceLabel).where(
                ChunkRelevanceLabel.project_id == project.id,
                ChunkRelevanceLabel.labeled_by == user.id,
            )
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
                    relevance=item.relevance,
                    content_preview=item.content_preview,
                    url=item.url,
                    title=item.title,
                    labeled_by=user.id,
                )
            )
        else:
            current.relevance = item.relevance
            if item.content_preview is not None:
                current.content_preview = item.content_preview
            if item.url is not None:
                current.url = item.url
            if item.title is not None:
                current.title = item.title
        saved += 1

    await db.flush()
    return {"saved": saved}


@router.get("/labeling/agreement", response_model=AgreementReport)
async def get_agreement(
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Inter-annotator agreement (Cohen's kappa) over chunks judged by more than one person.

    Documents how consistently the relevance criteria are applied and lists the chunks where
    annotators disagree, with the current gold verdict, for adjudication. ``available`` is False
    until at least two annotators have an overlapping judgment.
    """
    labels = (
        await db.execute(
            select(ChunkRelevanceLabel).where(ChunkRelevanceLabel.project_id == project.id)
        )
    ).scalars().all()

    labeler_ids = {lbl.labeled_by for lbl in labels if lbl.labeled_by}
    names: dict = {}
    if labeler_ids:
        users = (await db.execute(select(User).where(User.id.in_(labeler_ids)))).scalars().all()
        names = {u.id: (_display_name(u.email) or str(u.id)) for u in users}

    votes = [
        Vote(
            test_id=lbl.test_id,
            chunk_id=lbl.chunk_id,
            relevance=lbl.relevance,
            annotator_id=lbl.labeled_by,
            annotator_name=names.get(lbl.labeled_by, "unknown"),
            title=lbl.title,
        )
        for lbl in labels
    ]

    golds = (
        await db.execute(
            select(ChunkGoldLabel).where(ChunkGoldLabel.project_id == project.id)
        )
    ).scalars().all()
    overrides = {(g.test_id, g.chunk_id): g.relevance for g in golds}

    return build_agreement_report(votes, overrides)


@router.put(
    "/labeling/gold",
    dependencies=[require_write("evaluate", "labeling")],
)
async def set_gold(
    body: GoldUpdate,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Adjudicate a chunk's gold relevance grade (0..3), overriding the annotator consensus."""
    if not is_valid_grade(body.relevance):
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INVALID_GRADE",
                    "message": f"relevance must be an integer {GRADE_MIN}..{GRADE_MAX}",
                }
            },
        )
    gold = (
        await db.execute(
            select(ChunkGoldLabel).where(
                ChunkGoldLabel.project_id == project.id,
                ChunkGoldLabel.test_id == body.test_id,
                ChunkGoldLabel.chunk_id == body.chunk_id,
            )
        )
    ).scalar_one_or_none()
    if gold is None:
        db.add(
            ChunkGoldLabel(
                project_id=project.id,
                test_id=body.test_id,
                chunk_id=body.chunk_id,
                relevance=body.relevance,
                decided_by=user.id,
            )
        )
    else:
        gold.relevance = body.relevance
        gold.decided_by = user.id
    await db.flush()
    return {"test_id": body.test_id, "chunk_id": body.chunk_id, "relevance": body.relevance}
