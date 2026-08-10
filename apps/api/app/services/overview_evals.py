"""Evaluation pass rate over time, and dataset coverage progress.

Aggregated in Python from run rows rather than in SQL. That is a deliberate asymmetry
with the feedback and adoption sections, and it is justified: eval runs are
low-cardinality (hundreds per year, not millions), and excluding reruns requires reading
``EvalRun.run_metadata['rerun_of']``, a JSONB lookup that cannot run on the SQLite test
database because ``JSONB`` compiles to ``TEXT`` there. ``routers/eval_history.py`` already
sets this precedent.

``EvalRun.total`` and ``.passed`` already exclude degraded/errored results (see
``services/eval_executor.py``, which counts only ``execution_status == "ok"`` rows), so
the curve here *is* the headline pass rate without touching ``eval_results``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.datasets import TestCase, TestDataset
from app.models.evaluations import EvalResult, EvalRun
from app.models.project import Project
from app.schemas.overview_summary import (
    EvalBucketPoint,
    EvalLatestRun,
    EvalOverview,
    EvalProgress,
)
from app.services.failure_pattern import normalize_result_test_id
from app.services.time_buckets import Bucket, bucket_key, safe_rate

# Cases marked needs_work are excluded from the runnable suite, matching
# routers/eval_jobs.py and routers/eval_reports_router.py.
NEEDS_WORK = "needs_work"


def _parse_sources(sources: str | None) -> list[str]:
    """Comma-separated EvalRun.source allowlist, matching eval_history.py's convention."""
    if not sources:
        return []
    return [s.strip() for s in sources.split(",") if s.strip()]


async def _load_runs(
    db: AsyncSession,
    project: Project,
    *,
    start: datetime,
    end: datetime,
    include_reruns: bool,
    sources: list[str],
    run_limit: int,
) -> tuple[list, int]:
    """Runs in the window that contribute to the curve, plus the no-case exclusion count."""
    query = (
        select(
            EvalRun.id,
            EvalRun.name,
            EvalRun.created_at,
            EvalRun.source,
            EvalRun.total,
            EvalRun.passed,
            EvalRun.run_metadata,
        )
        .where(
            EvalRun.project_id == project.id,
            EvalRun.created_at >= start,
            EvalRun.created_at <= end,
        )
        .order_by(EvalRun.created_at.desc())
        .limit(run_limit)
    )
    if sources:
        query = query.where(EvalRun.source.in_(sources))
    rows = (await db.execute(query)).all()

    kept = []
    excluded_no_cases = 0
    for r in rows:
        if not include_reruns and (r.run_metadata or {}).get("rerun_of"):
            continue
        if not (r.total or 0):
            # Aborted, or every case landed in the DLQ. Including it would drag the
            # bucket's pass rate toward zero and inflate the "cases evaluated" count.
            excluded_no_cases += 1
            continue
        kept.append(r)
    kept.sort(key=lambda r: r.created_at)
    return kept, excluded_no_cases


async def _progress(
    db: AsyncSession, project: Project, *, dataset_id: str | None = None
) -> EvalProgress:
    """All-time dataset coverage: distinct runnable cases that have ever been evaluated."""
    runnable_q = (
        select(distinct(TestCase.test_id))
        .join(TestDataset, TestCase.dataset_id == TestDataset.id)
        .where(TestDataset.project_id == project.id, TestCase.status != NEEDS_WORK)
    )
    if dataset_id:
        runnable_q = runnable_q.where(TestCase.dataset_id == dataset_id)
    runnable = set((await db.execute(runnable_q)).scalars())

    # distinct() keeps this bounded by suite size rather than by result-row count.
    result_ids = (
        await db.execute(
            select(distinct(EvalResult.test_id))
            .join(EvalRun, EvalResult.run_id == EvalRun.id)
            .where(EvalRun.project_id == project.id, EvalResult.execution_status == "ok")
        )
    ).scalars()
    # Without normalization a case run in "both" filter mode appears as
    # "case [filtered]" and "case [unfiltered]" and would be counted twice, which can
    # push the numerator above the denominator.
    evaluated_ids = {normalize_result_test_id(t) for t in result_ids}

    evaluated = len(evaluated_ids & runnable)
    return EvalProgress(
        evaluated=evaluated,
        total=len(runnable),
        never_evaluated=len(runnable - evaluated_ids),
        evaluated_unknown=len(evaluated_ids - runnable),
        progress_rate=safe_rate(evaluated, len(runnable)),
    )


async def window_pass_rate(
    db: AsyncSession,
    project: Project,
    *,
    start: datetime,
    end: datetime,
    include_reruns: bool = True,
    sources: str | None = None,
    run_limit: int = 200,
) -> float | None:
    """Case-weighted pass rate for a window, for the previous-period comparison."""
    runs, _ = await _load_runs(
        db,
        project,
        start=start,
        end=end,
        include_reruns=include_reruns,
        sources=_parse_sources(sources),
        run_limit=run_limit,
    )
    cases = sum(r.total or 0 for r in runs)
    if not cases:
        return None
    return safe_rate(sum(r.passed or 0 for r in runs), cases)


async def compute_eval_overview(
    db: AsyncSession,
    project: Project,
    *,
    start: datetime,
    end: datetime,
    bucket: Bucket,
    axis: list[str],
    include_reruns: bool = True,
    sources: str | None = None,
    dataset_id: str | None = None,
    run_limit: int = 200,
) -> EvalOverview:
    runs, excluded_no_cases = await _load_runs(
        db,
        project,
        start=start,
        end=end,
        include_reruns=include_reruns,
        sources=_parse_sources(sources),
        run_limit=run_limit,
    )

    grouped: dict[str, list] = {label: [] for label in axis}
    for r in runs:
        label = bucket_key(r.created_at, bucket)
        if label in grouped:
            grouped[label].append(r)

    points: list[EvalBucketPoint] = []
    for label in axis:
        bucket_runs = grouped[label]
        cases = sum(r.total or 0 for r in bucket_runs)
        passed = sum(r.passed or 0 for r in bucket_runs)
        rates = [safe_rate(r.passed or 0, r.total or 0) for r in bucket_runs if r.total]
        points.append(
            EvalBucketPoint(
                bucket=label,
                run_count=len(bucket_runs),
                cases=cases,
                passed=passed,
                # None, not 0.0: a bucket with no run is a gap in the line, not a
                # collapse in quality.
                pass_rate=safe_rate(passed, cases) if cases else None,
                unweighted_pass_rate=round(sum(rates) / len(rates), 4) if rates else None,
            )
        )

    total_cases = sum(r.total or 0 for r in runs)
    total_passed = sum(r.passed or 0 for r in runs)
    latest = runs[-1] if runs else None

    return EvalOverview(
        points=points,
        window_pass_rate=safe_rate(total_passed, total_cases) if total_cases else None,
        current_pass_rate=(
            safe_rate(latest.passed or 0, latest.total or 0) if latest else None
        ),
        runs=len(runs),
        cases=total_cases,
        passed=total_passed,
        runs_excluded_no_cases=excluded_no_cases,
        progress=await _progress(db, project, dataset_id=dataset_id),
        latest_run=(
            EvalLatestRun(
                id=latest.id,
                name=latest.name,
                created_at=latest.created_at,
                source=latest.source,
                total=latest.total or 0,
                passed=latest.passed or 0,
                pass_rate=safe_rate(latest.passed or 0, latest.total or 0),
            )
            if latest
            else None
        ),
    )
