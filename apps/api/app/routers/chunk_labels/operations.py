"""Mutation + agreement endpoints for the chunk-labeling flow."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_write
from app.db import get_db
from app.models.chunk_labels import (
    AI_ANNOTATOR,
    GRADE_MAX,
    GRADE_MIN,
    SLICE_VALUES,
    ChunkGoldLabel,
    ChunkRelevanceLabel,
    TestCaseLabelingStatus,
    is_valid_grade,
)
from app.models.evaluations import EvalResult, EvalRun
from app.models.project import Project
from app.models.user import User
from app.schemas.retrieval import (
    AgreementReport,
    AiJudgeRequest,
    AiJudgeResponse,
    ChunkLabelBatch,
    GoldUpdate,
    LabelingSliceUpdate,
    LabelingStatusUpdate,
)
from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService
from app.services.chunk_agreement import Vote, build_agreement_report
from app.services.chunk_ai_judge import AiJudgeChunk, ai_judge_chunks
from app.services.llm_usage_tracker import record_llm_usage

from ._helpers import _display_name

router = APIRouter()


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


@router.delete(
    "/labels",
    dependencies=[require_write("evaluate", "labeling")],
)
async def delete_label(
    test_id: str,
    chunk_id: str,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Remove the calling user's relevance label for a (test_id, chunk_id) pair.

    Lets an annotator un-judge a chunk (clear its 0..3 grade). Only the caller's own label is
    deleted; other annotators' rows and any gold override are untouched. Idempotent: deleting a
    label that doesn't exist still succeeds, with ``deleted=False``.
    """
    label = (
        await db.execute(
            select(ChunkRelevanceLabel).where(
                ChunkRelevanceLabel.project_id == project.id,
                ChunkRelevanceLabel.labeled_by == user.id,
                ChunkRelevanceLabel.test_id == test_id,
                ChunkRelevanceLabel.chunk_id == chunk_id,
            )
        )
    ).scalar_one_or_none()
    if label is not None:
        await db.delete(label)
        await db.flush()
    return {"deleted": label is not None}


@router.post(
    "/labeling/ai-judge",
    response_model=AiJudgeResponse,
    dependencies=[require_write("evaluate", "labeling")],
)
async def ai_judge_case(
    body: AiJudgeRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Grade a test case's retrieved chunks with the LLM, stored under the ``AI`` annotator.

    A one-click second opinion: the model judges each chunk's relevance to the query on the same
    0..3 scale a human uses. The grades become labels attributed to the AI annotator — a distinct
    annotator in the agreement panel (so a lone human reviewer gets a Cohen's kappa against the
    model) but excluded from the gold that feeds the retrieval metrics. Re-running re-grades the
    same chunks (the AI annotator owns one label per chunk).
    """
    try:
        llm = AnalysisLlmService(user_settings=user.settings, project_settings=project.settings)
    except AnalysisLlmConfigError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "LLM_NOT_CONFIGURED", "message": str(exc)}},
        ) from exc

    # Most recent capture of the case (optionally pinned to a run), for its retrieved chunks.
    result_filter = [EvalResult.test_id == body.test_id, EvalRun.project_id == project.id]
    if body.run_id:
        result_filter.append(EvalRun.id == body.run_id)
    result = (
        await db.execute(
            select(EvalResult)
            .join(EvalRun, EvalResult.run_id == EvalRun.id)
            .where(*result_filter)
            .order_by(EvalRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Test case not found"}},
        )

    meta = result.result_metadata if isinstance(result.result_metadata, dict) else {}
    raw_chunks = meta.get("retrieved_chunks")
    raw_chunks = raw_chunks if isinstance(raw_chunks, list) else []
    # Only judgeable (chunk_id-bearing) chunks; keep their snapshot fields for the stored label.
    judgeable = [
        c
        for c in raw_chunks
        if isinstance(c, dict) and isinstance(c.get("chunk_id"), str)
    ]
    if not judgeable:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "NO_CHUNKS",
                    "message": "This case has no chunks with ids to judge.",
                }
            },
        )

    chunks = [
        AiJudgeChunk(chunk_id=c["chunk_id"], text=str(c.get("content") or c.get("content_preview") or ""))
        for c in judgeable
    ]
    try:
        grades, usage = await ai_judge_chunks(llm, str(result.input or ""), chunks)
    except AnalysisLlmConfigError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "LLM_NOT_CONFIGURED", "message": str(exc)}},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "AI_JUDGE_FAILED", "message": "The AI judge is unavailable. Try again."}},
        ) from exc

    await record_llm_usage(
        db,
        project_id=project.id,
        service_name="chunk_labeling",
        function_name="ai_judge",
        provider=llm.provider,
        model=llm.model,
        usage=usage,
        request_metadata={"test_id": body.test_id, "chunks": len(chunks)},
    )

    # Upsert the AI annotator's own labels (one per chunk). AI rows carry annotator=AI and no
    # user, so they never collide with a human's label for the same chunk.
    existing = (
        await db.execute(
            select(ChunkRelevanceLabel).where(
                ChunkRelevanceLabel.project_id == project.id,
                ChunkRelevanceLabel.test_id == body.test_id,
                ChunkRelevanceLabel.annotator == AI_ANNOTATOR,
            )
        )
    ).scalars().all()
    by_chunk = {lbl.chunk_id: lbl for lbl in existing}
    snapshots = {c["chunk_id"]: c for c in judgeable}

    for chunk_id, grade in grades.items():
        snap = snapshots.get(chunk_id, {})
        current = by_chunk.get(chunk_id)
        if current is None:
            db.add(
                ChunkRelevanceLabel(
                    project_id=project.id,
                    test_id=body.test_id,
                    chunk_id=chunk_id,
                    relevance=grade,
                    content_preview=snap.get("content_preview"),
                    url=snap.get("url"),
                    title=snap.get("title"),
                    annotator=AI_ANNOTATOR,
                    labeled_by=None,
                )
            )
        else:
            current.relevance = grade

    await db.flush()
    return AiJudgeResponse(test_id=body.test_id, grades=grades, judged=len(grades))


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

    labeler_ids = {lbl.labeled_by for lbl in labels if lbl.labeled_by and not lbl.annotator}
    names: dict = {}
    if labeler_ids:
        users = (await db.execute(select(User).where(User.id.in_(labeler_ids)))).scalars().all()
        names = {u.id: (_display_name(u.email) or str(u.id)) for u in users}

    # A label's annotator identity is its ``annotator`` value (the AI judge) when set, else the
    # human who authored it. Both become distinct annotators in the agreement computation, so a
    # single human reviewer plus the AI judge already produces a Cohen's kappa.
    votes = [
        Vote(
            test_id=lbl.test_id,
            chunk_id=lbl.chunk_id,
            relevance=lbl.relevance,
            annotator_id=f"ai:{lbl.annotator}" if lbl.annotator else lbl.labeled_by,
            annotator_name=lbl.annotator or names.get(lbl.labeled_by, "unknown"),
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
