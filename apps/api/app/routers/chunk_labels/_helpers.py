"""Shared helpers + constants for the chunk-labeling endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk_labels import ChunkRelevanceLabel
from app.models.evaluations import EvalResult, EvalRun
from app.models.project import Project
from app.models.user import User
from app.services.chunk_pool import PooledChunk, PoolResult


def _display_name(email: str | None) -> str | None:
    """Compact display name for a labeler — the local part of their email."""
    if not email:
        return None
    return email.split("@", 1)[0]


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
) -> tuple[
    dict[tuple[str, str], int],
    dict[tuple[str, str], str],
    dict[str, list[str]],
    dict[tuple[str, str], int],
]:
    """Load chunk labels for the labeling view, scoped to one annotator's own judgments.

    Returns ``(labels_by_key, labeler_by_key, labelers_by_test, ai_labels_by_key)``. The first
    two are scoped to the human ``user_id`` (so each annotator sees and edits their *own* graded
    verdicts), keyed by ``(test_id, chunk_id)`` — ``labels_by_key`` maps to the 0..3 grade. AI
    judge labels (``annotator`` set) are never the viewer's own; they are returned separately in
    ``ai_labels_by_key`` so the UI can show the model's grade as a read-only second opinion.
    ``labelers_by_test`` lists every annotator (humans by name + the AI judge) who has judged any
    chunk in a test case, for the per-case "who labeled" display.
    """
    labels = (
        await db.execute(
            select(ChunkRelevanceLabel).where(ChunkRelevanceLabel.project_id == project.id)
        )
    ).scalars().all()

    labeler_ids = {lbl.labeled_by for lbl in labels if lbl.labeled_by and not lbl.annotator}
    names: dict = {}
    if labeler_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(labeler_ids)))
        ).scalars().all()
        names = {u.id: _display_name(u.email) for u in users}

    # The viewer's own labels are human rows (annotator NULL) authored by user_id.
    scoped = [
        lbl
        for lbl in labels
        if not lbl.annotator and (user_id is None or lbl.labeled_by == user_id)
    ]
    labels_by_key = {(lbl.test_id, lbl.chunk_id): lbl.relevance for lbl in scoped}
    labeler_by_key = {
        (lbl.test_id, lbl.chunk_id): names.get(lbl.labeled_by)
        for lbl in scoped
        if lbl.labeled_by and names.get(lbl.labeled_by)
    }

    ai_labels_by_key = {
        (lbl.test_id, lbl.chunk_id): lbl.relevance for lbl in labels if lbl.annotator
    }

    labelers_by_test: dict[str, list[str]] = {}
    for lbl in labels:
        # A non-human label is attributed to its annotator name (e.g. "AI"); a human label to
        # the display name of the user who made it.
        name = lbl.annotator or names.get(lbl.labeled_by)
        if name and name not in labelers_by_test.setdefault(lbl.test_id, []):
            labelers_by_test[lbl.test_id].append(name)
    return labels_by_key, labeler_by_key, labelers_by_test, ai_labels_by_key


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
