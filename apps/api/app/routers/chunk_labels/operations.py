"""Mutation + agreement endpoints for the chunk-labeling flow (human label CRUD).

The LLM-backed operations (AI judge, query planner) live in ``llm_ops.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_write
from app.db import get_db
from app.models.chunk_labels import (
    GRADE_MAX,
    GRADE_MIN,
    SLICE_VALUES,
    ChunkGoldLabel,
    ChunkRelevanceLabel,
    TestCaseLabelingStatus,
    is_valid_grade,
)
from app.models.passage_labels import (
    PASSAGE_SOURCES,
    PassageRelevanceLabel,
    is_valid_passage_relevance,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.retrieval import (
    AgreementReport,
    ChunkLabelBatch,
    GoldUpdate,
    LabelingSliceUpdate,
    LabelingStatusUpdate,
    PassageSelectionUpsert,
)
from app.services.chunk_agreement import Vote, build_agreement_report

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


@router.post(
    "/passage-labels",
    dependencies=[require_write("evaluate", "labeling")],
)
async def upsert_passage_labels(
    body: PassageSelectionUpsert,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Create or update the current user's passage selections for one chunk under a test case.

    An additive refinement of chunk labeling: within a chunk the labeler judged relevant, each
    passage is marked helps (``relevant=1``) or does-not-help (``relevant=0``). Rows are
    per-annotator (keyed by ``(test_id, chunk_id, passage_id, labeled_by)``), so this only ever
    touches the caller's own selections — the chunk label and other annotators are untouched.
    """
    for item in body.passages:
        if not is_valid_passage_relevance(item.relevant):
            raise HTTPException(
                status_code=422,
                detail={
                    "error": {
                        "code": "INVALID_PASSAGE_GRADE",
                        "message": "relevant must be 0 or 1",
                    }
                },
            )
        if item.passage_source not in PASSAGE_SOURCES:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": {
                        "code": "INVALID_PASSAGE_SOURCE",
                        "message": f"passage_source must be one of {PASSAGE_SOURCES}",
                    }
                },
            )

    existing = (
        await db.execute(
            select(PassageRelevanceLabel).where(
                PassageRelevanceLabel.project_id == project.id,
                PassageRelevanceLabel.labeled_by == user.id,
                PassageRelevanceLabel.test_id == body.test_id,
                PassageRelevanceLabel.chunk_id == body.chunk_id,
            )
        )
    ).scalars().all()
    by_pid = {lbl.passage_id: lbl for lbl in existing}

    saved = 0
    for item in body.passages:
        current = by_pid.get(item.passage_id)
        if current is None:
            db.add(
                PassageRelevanceLabel(
                    project_id=project.id,
                    test_id=body.test_id,
                    chunk_id=body.chunk_id,
                    passage_id=item.passage_id,
                    relevant=item.relevant,
                    passage_source=item.passage_source,
                    section_path=item.section_path,
                    text_preview=item.text_preview,
                    labeled_by=user.id,
                )
            )
        else:
            current.relevant = item.relevant
            current.passage_source = item.passage_source
            if item.section_path is not None:
                current.section_path = item.section_path
            if item.text_preview is not None:
                current.text_preview = item.text_preview
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
