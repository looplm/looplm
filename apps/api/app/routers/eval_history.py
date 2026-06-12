"""Cross-run test case failure history.

Aggregates EvalResult rows across recent runs per (normalized) test_id so the
UI can show which test cases fail how often and why. Aggregation happens in
Python on narrow-column selects — no JSONB SQL operators — so the SQLite-backed
test suite exercises the same code path as Postgres.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section
from app.db import get_db
from app.models.models import EvalResult, EvalRun, TestCase, TestDataset
from app.models.project import Project
from app.schemas.eval_history import (
    TestCaseHistoryItem,
    TestCaseHistoryResponse,
    TestCaseTrendPoint,
)
from app.services.failure_pattern import normalize_result_test_id

router = APIRouter(
    tags=["evaluations"],
    dependencies=[require_section("evaluate", "evaluations")],
)


@router.get("/test-case-history", response_model=TestCaseHistoryResponse)
async def get_test_case_history(
    dataset_id: UUID | None = None,
    run_limit: int = Query(20, ge=1, le=100),
    min_failures: int = Query(0, ge=0),
    include_reruns: bool = Query(True),
    sources: str | None = Query(None, description="Comma-separated run sources, e.g. 'triggered'"),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    # 1. Window of recent runs
    runs_query = (
        select(EvalRun.id, EvalRun.created_at, EvalRun.run_metadata)
        .where(EvalRun.project_id == project.id)
        .order_by(EvalRun.created_at.desc())
        .limit(run_limit)
    )
    if sources:
        wanted_sources = {s.strip() for s in sources.split(",") if s.strip()}
        if wanted_sources:
            runs_query = runs_query.where(EvalRun.source.in_(wanted_sources))
    run_rows = (await db.execute(runs_query)).all()

    rerun_run_ids = {r.id for r in run_rows if (r.run_metadata or {}).get("rerun_of")}
    if not include_reruns:
        run_rows = [r for r in run_rows if r.id not in rerun_run_ids]

    run_created_at = {r.id: r.created_at for r in run_rows}
    if not run_rows:
        return TestCaseHistoryResponse(data=[], runs_considered=0, oldest_run_at=None)

    # 2. Result rows for the window — narrow columns only (no input/output blobs)
    result_rows = (await db.execute(
        select(
            EvalResult.run_id,
            EvalResult.test_id,
            EvalResult.pass_,
            EvalResult.result_metadata,
        ).where(EvalResult.run_id.in_(run_created_at.keys()))
    )).all()

    # 3. Aggregate per (normalized test_id, run): failed = any variant row failed
    per_case_runs: dict[str, dict[UUID, bool]] = defaultdict(dict)
    pattern_counts: dict[str, Counter] = defaultdict(Counter)
    root_cause_counts: dict[str, Counter] = defaultdict(Counter)
    unclassified: Counter = Counter()

    for row in result_rows:
        tid = normalize_result_test_id(row.test_id)
        prev = per_case_runs[tid].get(row.run_id, True)
        per_case_runs[tid][row.run_id] = prev and row.pass_
        if not row.pass_:
            meta = row.result_metadata or {}
            pattern = meta.get("failure_pattern")
            if pattern:
                pattern_counts[tid][pattern] += 1
            root_cause = (meta.get("root_cause") or {}).get("category")
            if root_cause:
                root_cause_counts[tid][root_cause] += 1
            if not pattern and not root_cause:
                unclassified[tid] += 1

    # 4. Current test case existence / dataset mapping. test_id is not unique
    # across datasets — first match wins, which is acceptable for display.
    case_rows = (await db.execute(
        select(TestCase.test_id, TestCase.dataset_id, TestCase.status, TestDataset.name)
        .join(TestDataset)
        .where(TestDataset.project_id == project.id)
    )).all()
    case_info: dict[str, tuple[UUID, str, str]] = {}
    for row in case_rows:
        case_info.setdefault(row.test_id, (row.dataset_id, row.status, row.name))

    items: list[TestCaseHistoryItem] = []
    for tid, runs_map in per_case_runs.items():
        info = case_info.get(tid)
        if dataset_id and (not info or info[0] != dataset_id):
            continue

        pass_count = sum(1 for passed in runs_map.values() if passed)
        fail_count = len(runs_map) - pass_count
        if fail_count < min_failures:
            continue

        trend = sorted(
            (
                TestCaseTrendPoint(
                    run_id=rid,
                    created_at=run_created_at[rid],
                    passed=passed,
                    is_rerun=rid in rerun_run_ids,
                )
                for rid, passed in runs_map.items()
            ),
            key=lambda p: p.created_at,
            reverse=True,
        )
        failed_points = [p for p in trend if not p.passed]
        dominant_pattern = pattern_counts[tid].most_common(1)
        dominant_root_cause = root_cause_counts[tid].most_common(1)

        items.append(TestCaseHistoryItem(
            test_id=tid,
            dataset_id=info[0] if info else None,
            dataset_name=info[2] if info else None,
            case_status=info[1] if info else None,
            exists=info is not None,
            runs_participated=len(runs_map),
            pass_count=pass_count,
            fail_count=fail_count,
            pass_rate=pass_count / len(runs_map) if runs_map else 0.0,
            dominant_failure_pattern=dominant_pattern[0][0] if dominant_pattern else None,
            dominant_failure_pattern_count=dominant_pattern[0][1] if dominant_pattern else 0,
            dominant_root_cause=dominant_root_cause[0][0] if dominant_root_cause else None,
            dominant_root_cause_count=dominant_root_cause[0][1] if dominant_root_cause else 0,
            unclassified_failures=unclassified.get(tid, 0),
            last_failed_at=failed_points[0].created_at if failed_points else None,
            last_failed_run_id=failed_points[0].run_id if failed_points else None,
            trend=trend,
        ))

    items.sort(key=lambda i: (-i.fail_count, i.test_id))

    return TestCaseHistoryResponse(
        data=items,
        runs_considered=len(run_rows),
        oldest_run_at=min(run_created_at.values()) if run_created_at else None,
    )
