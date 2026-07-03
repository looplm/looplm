"""Cross-dataset duplicate-question detection endpoints (sub-router of datasets).

Scans every test-case prompt in the project, groups exact / near duplicates,
and offers resolution: merge redundant cases into one, or dismiss a group as
'not a duplicate' so it stops resurfacing.
"""

from __future__ import annotations

from itertools import combinations
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_write
from app.db import get_db
from app.models.datasets import DatasetDuplicateDismissal
from app.models.models import TestCase, TestDataset
from app.models.project import Project
from app.schemas.datasets import (
    DuplicateDismissRequest,
    DuplicateMergeRequest,
    DuplicatesResponse,
    TestCaseItem,
)
from app.services.duplicate_detection import (
    _pair_key,
    find_duplicate_groups,
    merge_case_fields,
    merge_case_labeling,
)

from .dataset_helpers import _tc_to_item

router = APIRouter(tags=["datasets"])


async def _load_project_cases(db: AsyncSession, project: Project) -> list[dict]:
    """Load every test case in the project joined with its dataset name."""
    rows = (
        await db.execute(
            select(
                TestCase.id,
                TestCase.dataset_id,
                TestDataset.name,
                TestCase.test_id,
                TestCase.prompt,
                TestCase.expected_answer,
                TestCase.status,
            )
            .join(TestDataset, TestCase.dataset_id == TestDataset.id)
            .where(TestDataset.project_id == project.id)
        )
    ).all()
    return [
        {
            "id": r.id,
            "dataset_id": r.dataset_id,
            "dataset_name": r.name,
            "test_id": r.test_id,
            "prompt": r.prompt,
            "expected_answer": r.expected_answer,
            "status": r.status,
        }
        for r in rows
    ]


async def _load_dismissed_pairs(db: AsyncSession, project: Project) -> set[tuple[str, str]]:
    rows = (
        await db.execute(
            select(DatasetDuplicateDismissal.case_id_a, DatasetDuplicateDismissal.case_id_b)
            .where(DatasetDuplicateDismissal.project_id == project.id)
        )
    ).all()
    return {_pair_key(str(a), str(b)) for a, b in rows}


@router.get("/duplicates", response_model=DuplicatesResponse)
async def list_duplicates(
    threshold: float = Query(0.8, ge=0.5, le=1.0),
    scope: str = Query("all", pattern="^(all|within_dataset)$"),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Return duplicate / near-duplicate groups across all datasets in the project."""
    cases = await _load_project_cases(db, project)
    dismissed = await _load_dismissed_pairs(db, project)
    groups = find_duplicate_groups(
        cases, threshold=threshold, scope=scope, dismissed_pairs=dismissed
    )
    duplicate_cases = sum(len(g["members"]) for g in groups)
    return DuplicatesResponse(
        groups=groups,
        threshold=threshold,
        scope=scope,
        total_cases=len(cases),
        duplicate_cases=duplicate_cases,
    )


async def _fetch_project_cases_by_id(
    db: AsyncSession, project: Project, case_ids: list[UUID]
) -> dict[UUID, TestCase]:
    """Fetch the given cases, scoped to the project. Raises 404 on any miss."""
    rows = (
        await db.execute(
            select(TestCase)
            .join(TestDataset, TestCase.dataset_id == TestDataset.id)
            .where(TestCase.id.in_(case_ids), TestDataset.project_id == project.id)
        )
    ).scalars().all()
    found = {tc.id: tc for tc in rows}
    missing = [cid for cid in case_ids if cid not in found]
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Test case not found"}},
        )
    return found


@router.post(
    "/duplicates/merge",
    response_model=TestCaseItem,
    dependencies=[require_write("evaluate", "datasets")],
)
async def merge_duplicates(
    body: DuplicateMergeRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Merge ``merge_case_ids`` into ``keep_case_id`` and delete the merged ones.

    List fields are unioned and empty scalars on the kept case are backfilled;
    the kept case wins on conflicting context-filter / metadata keys. The merged
    cases' chunk-relevance labels, gold verdicts, and labeling status (which the
    retrieval metrics are derived from, all keyed by ``test_id``) are re-pointed
    onto the kept case so no labeling effort is lost.
    """
    merge_ids = [cid for cid in body.merge_case_ids if cid != body.keep_case_id]
    if not merge_ids:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "INVALID", "message": "Nothing to merge"}},
        )

    cases = await _fetch_project_cases_by_id(db, project, [body.keep_case_id, *merge_ids])
    keep = cases[body.keep_case_id]
    others = [cases[cid] for cid in merge_ids]

    merge_case_fields(keep, others)
    await merge_case_labeling(
        db, project.id, keep.test_id, [o.test_id for o in others]
    )
    for other in others:
        await db.delete(other)

    await db.flush()
    await db.refresh(keep)
    return _tc_to_item(keep)


@router.post(
    "/duplicates/dismiss",
    status_code=204,
    dependencies=[require_write("evaluate", "datasets")],
)
async def dismiss_duplicates(
    body: DuplicateDismissRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Record every pair among ``case_ids`` as a confirmed non-duplicate."""
    # Validate all cases belong to the project.
    await _fetch_project_cases_by_id(db, project, body.case_ids)

    existing = await _load_dismissed_pairs(db, project)
    for a, b in combinations(body.case_ids, 2):
        key = _pair_key(str(a), str(b))
        if key in existing:
            continue
        existing.add(key)
        db.add(
            DatasetDuplicateDismissal(
                project_id=project.id,
                case_id_a=UUID(key[0]),
                case_id_b=UUID(key[1]),
            )
        )
    await db.flush()
