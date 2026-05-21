"""Evaluation run endpoints."""
from __future__ import annotations

import json
import logging
from math import ceil
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, require_section, require_write
from app.db import get_db
from app.models.models import EvalResult, EvalRun
from app.models.project import Project
from app.schemas.evaluations import (
    EvalImportRequest,
    EvalResultItem,
    EvalResultSummary,
    EvalRunDetail,
    EvalRunListItem,
    EvalRunListResponse,
    EvalRunStats,
    GraderResultSummary,
    GraderSummaryItem,
    PaginationInfo,
    ScoreSummaryItem,
)

def _enrich_result_metadata(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Enrich eval result metadata with retrieval_context extracted from raw_response."""
    meta = meta or {}
    if "retrieval_context" in meta:
        return meta
    raw = meta.get("raw_response")
    if not raw:
        return meta
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return meta
    if not isinstance(parsed, dict):
        return meta
    ctx = parsed.get("retrieval_context") or parsed.get("retrievalContext") or parsed.get("context")
    if ctx:
        enriched = dict(meta)
        if isinstance(ctx, str):
            enriched["retrieval_context"] = ctx[:10000]
        elif isinstance(ctx, (dict, list)):
            enriched["retrieval_context"] = json.dumps(ctx, ensure_ascii=False, default=str)[:10000]
        return enriched
    return meta


from .eval_helpers import (
    _compute_summaries,
    _import_eval_run_from_body,
    _is_legacy_eval_import_format,
    _recompute_stats_excluding,
    _transform_legacy_eval_import,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evals", tags=["evaluations"], dependencies=[require_section("evaluate", "evaluations")])


# ── Fixed-path routes (must come before /{run_id} parameterized routes) ──


@router.post("/import", response_model=EvalRunListItem, dependencies=[require_write("evaluate", "evaluations")])
async def import_eval_run(
    request: Request,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    raw = await request.json()

    # Auto-detect legacy eval import format and transform
    if _is_legacy_eval_import_format(raw):
        logger.info("Detected legacy eval import format, transforming")
        test_cases = raw.get("testCases")  # optionally embedded
        body = _transform_legacy_eval_import(raw, test_cases)
    else:
        body = EvalImportRequest(**raw)

    run, total, passed, grader_summary, score_summary = await _import_eval_run_from_body(
        raw, body, project, db,
    )

    failed = total - passed
    pass_rate = passed / total if total > 0 else 0.0
    return EvalRunListItem(
        id=run.id,
        name=run.name,
        source=run.source,
        tags=run.tags,
        total=total,
        passed=passed,
        failed=failed,
        pass_rate=pass_rate,
        grader_summary={k: GraderSummaryItem(**v) for k, v in grader_summary.items()},
        score_summary={k: ScoreSummaryItem(**v) for k, v in score_summary.items()},
        metadata=body.metadata,
        created_at=run.created_at,
    )


@router.get("", response_model=EvalRunListResponse)
async def list_eval_runs(
    source: str | None = None,
    tag: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    base_filter = [EvalRun.project_id == project.id]

    if source:
        base_filter.append(EvalRun.source == source)
    if tag:
        base_filter.append(EvalRun.tags.contains([tag]))

    count_query = select(func.count(EvalRun.id)).where(*base_filter)
    total = (await db.execute(count_query)).scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = (
        select(EvalRun)
        .where(*base_filter)
        .order_by(EvalRun.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(query)
    runs = result.scalars().all()

    data = []
    for run in runs:
        graded_total = run.passed + run.failed
        pass_rate = run.passed / graded_total if graded_total > 0 else 0.0
        data.append(
            EvalRunListItem(
                id=run.id,
                name=run.name,
                source=run.source,
                tags=run.tags,
                total=graded_total,
                passed=run.passed,
                failed=run.failed,
                pass_rate=pass_rate,
                grader_summary={k: GraderSummaryItem(**v) for k, v in (run.grader_summary or {}).items()},
                score_summary={k: ScoreSummaryItem(**v) for k, v in (run.score_summary or {}).items()},
                metadata=run.run_metadata or {},
                created_at=run.created_at,
            )
        )

    return EvalRunListResponse(
        data=data,
        pagination=PaginationInfo(page=page, per_page=per_page, total=total, total_pages=total_pages),
    )


# ── Include sub-routers (fixed-path routes — before /{run_id}) ──

from .eval_jobs import router as eval_jobs_router
from .eval_reports_router import router as eval_reports_router
from .eval_sessions import router as eval_sessions_router

router.include_router(eval_jobs_router)
router.include_router(eval_reports_router)
router.include_router(eval_sessions_router)


# ── Parameterized routes (/{run_id}) — must come last ────────


def _summarize_graders(graders: dict[str, Any] | None) -> dict[str, GraderResultSummary]:
    """Trim each grader to (pass, reason, skipped) for the list payload."""
    out: dict[str, GraderResultSummary] = {}
    for name, g in (graders or {}).items():
        if not isinstance(g, dict):
            continue
        out[name] = GraderResultSummary(
            **{"pass": bool(g.get("pass", False))},
            reason=g.get("reason"),
            skipped=bool(g.get("skipped", False)),
        )
    return out


def _turn_count(metadata: dict[str, Any] | None) -> int | None:
    history = (metadata or {}).get("conversation_history")
    if isinstance(history, list):
        return len(history)
    return None


@router.get("/{run_id}", response_model=EvalRunDetail)
async def get_eval_run(
    run_id: UUID,
    pass_filter: bool | None = Query(None, alias="pass"),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(EvalRun).where(EvalRun.id == run_id, EvalRun.project_id == project.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Eval run not found"}})

    # Only select the columns the table needs. We pull `result_metadata` solely
    # to derive `turn_count`; the full blob is not returned.
    results_query = select(
        EvalResult.id,
        EvalResult.test_id,
        EvalResult.pass_,
        EvalResult.tags,
        EvalResult.graders,
        EvalResult.turns_to_pass,
        EvalResult.result_metadata,
        EvalResult.created_at,
    ).where(EvalResult.run_id == run.id)
    if pass_filter is not None:
        results_query = results_query.where(EvalResult.pass_ == pass_filter)
    results_query = results_query.order_by(EvalResult.test_id)

    results_result = await db.execute(results_query)
    rows = results_result.all()

    pass_rate = run.passed / run.total if run.total > 0 else 0.0

    return EvalRunDetail(
        id=run.id,
        name=run.name,
        source=run.source,
        tags=run.tags,
        total=run.total,
        passed=run.passed,
        failed=run.failed,
        pass_rate=pass_rate,
        grader_summary={k: GraderSummaryItem(**v) for k, v in (run.grader_summary or {}).items()},
        score_summary={k: ScoreSummaryItem(**v) for k, v in (run.score_summary or {}).items()},
        metadata=run.run_metadata or {},
        created_at=run.created_at,
        results=[
            EvalResultSummary(
                id=r.id,
                test_id=r.test_id,
                **{"pass": r.pass_},
                tags=r.tags or [],
                graders=_summarize_graders(r.graders),
                turns_to_pass=r.turns_to_pass,
                turn_count=_turn_count(r.result_metadata),
                created_at=r.created_at,
            )
            for r in rows
        ],
    )


@router.get("/{run_id}/results/{result_id}", response_model=EvalResultItem)
async def get_eval_result(
    run_id: UUID,
    result_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Return a single eval result with full input/output/metadata. Used by the row modal."""
    result = await db.execute(
        select(EvalResult)
        .join(EvalRun, EvalResult.run_id == EvalRun.id)
        .where(
            EvalResult.id == result_id,
            EvalResult.run_id == run_id,
            EvalRun.project_id == project.id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Eval result not found"}})

    return EvalResultItem(
        id=row.id,
        test_id=row.test_id,
        **{"pass": row.pass_},
        reason=row.reason,
        input=row.input,
        output=row.output,
        expected_output=row.expected_output,
        tags=row.tags or [],
        graders=row.graders or {},
        scores=row.scores or {},
        metadata=_enrich_result_metadata(row.result_metadata),
        turns_to_pass=row.turns_to_pass,
        created_at=row.created_at,
    )


@router.get("/{run_id}/stats", response_model=EvalRunStats)
async def get_eval_run_stats(
    run_id: UUID,
    exclude_graders: str | None = Query(None, description="Comma-separated grader names to exclude"),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(EvalRun).where(EvalRun.id == run_id, EvalRun.project_id == project.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Eval run not found"}})

    if not exclude_graders:
        pass_rate = run.passed / run.total if run.total > 0 else 0.0
        return EvalRunStats(
            total=run.total,
            passed=run.passed,
            failed=run.failed,
            pass_rate=pass_rate,
            grader_summary={k: GraderSummaryItem(**v) for k, v in (run.grader_summary or {}).items()},
            score_summary={k: ScoreSummaryItem(**v) for k, v in (run.score_summary or {}).items()},
        )

    # Recompute with excluded graders
    excluded = {g.strip() for g in exclude_graders.split(",")}
    results_result = await db.execute(
        select(EvalResult).where(EvalResult.run_id == run.id)
    )
    results = results_result.scalars().all()

    total, passed, failed, grader_summary, score_summary = _recompute_stats_excluding(
        results, excluded, _compute_summaries,
    )

    return EvalRunStats(
        total=total,
        passed=passed,
        failed=failed,
        pass_rate=passed / total if total > 0 else 0.0,
        grader_summary={k: GraderSummaryItem(**v) for k, v in grader_summary.items()},
        score_summary={k: ScoreSummaryItem(**v) for k, v in score_summary.items()},
    )


@router.delete("/{run_id}", status_code=204, dependencies=[require_write("evaluate", "evaluations")])
async def delete_eval_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    result = await db.execute(
        select(EvalRun).where(EvalRun.id == run_id, EvalRun.project_id == project.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Eval run not found"}})

    await db.delete(run)
