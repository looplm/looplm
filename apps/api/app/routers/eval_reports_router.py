"""Evaluation report generation & CRUD endpoints."""
from __future__ import annotations

import asyncio
import logging
from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_project, get_current_user, require_section, require_write
from app.config import settings
from app.db import get_db
from app.models.models import EvalJob, EvalJobStatus, EvalReport, EvalResult, EvalRun, Evaluator, TestDataset
from app.models.project import Project
from app.models.user import User
from app.services.analysis_llm import merge_llm_settings
from app.schemas.eval_trigger import TriggerEvalResponse
from app.schemas.evaluations import (
    EvalReportDetail,
    EvalReportListItem,
    EvalReportListResponse,
    EvalReportResponse,
    MultiRunReportRequest,
    MultiRunReportResponse,
    PaginationInfo,
)

from .eval_helpers import (
    _get_eval_endpoint,
    _run_eval_background,
)
from .eval_jobs import _eval_tasks

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["evaluations"],
    dependencies=[require_section("evaluate", "evaluations")],
)


# ── Report Endpoints (before /{run_id}) ───────────────────────


@router.post(
    "/report",
    response_model=MultiRunReportResponse,
    dependencies=[require_write("evaluate", "evaluations")],
)
async def generate_multi_run_report(
    body: MultiRunReportRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Generate a markdown report aggregating multiple eval runs."""
    from app.services.analysis_llm import AnalysisLlmService
    from app.services.eval_report_multi import (
        generate_multi_run_markdown_report,
        generate_multi_run_recommendations,
    )

    # Load all requested runs (filtered by project)
    result = await db.execute(
        select(EvalRun).where(
            EvalRun.id.in_(body.run_ids),
            EvalRun.project_id == project.id,
        )
    )
    runs = list(result.scalars().all())

    if len(runs) != len(body.run_ids):
        found_ids = {r.id for r in runs}
        missing = [str(rid) for rid in body.run_ids if rid not in found_ids]
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": f"Eval runs not found: {', '.join(missing)}"}},
        )

    # Load all results for these runs in a single query
    all_results_result = await db.execute(
        select(EvalResult).where(EvalResult.run_id.in_(body.run_ids)).order_by(EvalResult.test_id)
    )
    all_results = list(all_results_result.scalars().all())

    # Group results by run_id
    results_by_run: dict[UUID, list[EvalResult]] = {}
    for r in all_results:
        results_by_run.setdefault(r.run_id, []).append(r)

    # Load evaluators
    ev_result = await db.execute(
        select(Evaluator).where(Evaluator.project_id == project.id)
    )
    evaluators = list(ev_result.scalars().all())

    # Filter evaluators by relevance if requested
    included_graders: set[str] | None = None
    if body.relevance_filter:
        filtered_evaluators = [e for e in evaluators if e.relevance in body.relevance_filter]
        included_graders = {e.name for e in filtered_evaluators}
    else:
        filtered_evaluators = evaluators

    # Build runs_with_results in the order requested
    run_map = {r.id: r for r in runs}
    runs_with_results = [
        (run_map[rid], results_by_run.get(rid, []))
        for rid in body.run_ids
        if rid in run_map
    ]

    markdown, per_run_reports = generate_multi_run_markdown_report(
        runs_with_results, filtered_evaluators, included_graders=included_graders,
    )

    # Generate LLM recommendations if there are failures
    total_failed = sum(r["summary"]["failed"] for r in per_run_reports)
    if total_failed > 0:
        try:
            llm = AnalysisLlmService(
                user_settings=dict(user.settings or {}), project_settings=project.settings
            )
            recommendations = await generate_multi_run_recommendations(llm, per_run_reports, db=db, project_id=project.id)
            markdown = markdown.replace("{{RECOMMENDATIONS}}", recommendations)
        except Exception as e:
            logger.warning("Could not generate multi-run recommendations: %s", e)
            markdown = markdown.replace("{{RECOMMENDATIONS}}", "_Could not generate recommendations._")

    total_tests = sum(len(results_by_run.get(rid, [])) for rid in body.run_ids)

    # Build a title from run names
    run_names = [run_map[rid].name for rid in body.run_ids if rid in run_map]
    if len(run_names) == 1:
        title = f"Report: {run_names[0]}"
    else:
        title = f"Report: {len(run_names)} runs"

    # Persist the report
    report = EvalReport(
        project_id=project.id,
        title=title,
        report_type="multi_run" if len(runs) > 1 else "single_run",
        markdown=markdown,
        run_ids=[str(rid) for rid in body.run_ids],
        run_count=len(runs),
        total_tests=total_tests,
    )
    db.add(report)
    await db.flush()
    await db.refresh(report)

    return MultiRunReportResponse(
        id=report.id,
        markdown=markdown,
        run_count=len(runs),
        total_tests=total_tests,
    )


@router.get("/reports", response_model=EvalReportListResponse)
async def list_eval_reports(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """List saved evaluation reports."""
    base_filter = [EvalReport.project_id == project.id]

    count_query = select(func.count(EvalReport.id)).where(*base_filter)
    total = (await db.execute(count_query)).scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = (
        select(EvalReport)
        .where(*base_filter)
        .order_by(EvalReport.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(query)
    reports = result.scalars().all()

    return EvalReportListResponse(
        data=[EvalReportListItem.model_validate(r) for r in reports],
        pagination=PaginationInfo(page=page, per_page=per_page, total=total, total_pages=total_pages),
    )


@router.get("/reports/{report_id}", response_model=EvalReportDetail)
async def get_eval_report_by_id(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Get a saved evaluation report."""
    result = await db.execute(
        select(EvalReport).where(EvalReport.id == report_id, EvalReport.project_id == project.id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Report not found"}})
    return EvalReportDetail.model_validate(report)


@router.delete("/reports/{report_id}", status_code=204, dependencies=[require_write("evaluate", "evaluations")])
async def delete_eval_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
):
    """Delete a saved evaluation report."""
    result = await db.execute(
        select(EvalReport).where(EvalReport.id == report_id, EvalReport.project_id == project.id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Report not found"}})
    await db.delete(report)


@router.get("/{run_id}/report", response_model=EvalReportResponse)
async def get_eval_report(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Generate a structured evaluation report for a run.

    Includes summary stats, failure analysis with trace info,
    and LLM-generated recommendations.
    """
    from app.services.analysis_llm import AnalysisLlmService
    from app.services.eval_report import generate_eval_report, generate_recommendations

    # Load run
    result = await db.execute(
        select(EvalRun).where(EvalRun.id == run_id, EvalRun.project_id == project.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Eval run not found"}},
        )

    # Load results
    results_result = await db.execute(
        select(EvalResult).where(EvalResult.run_id == run.id).order_by(EvalResult.test_id)
    )
    results = list(results_result.scalars().all())

    # Load evaluators for this project
    ev_result = await db.execute(
        select(Evaluator).where(Evaluator.project_id == project.id)
    )
    evaluators = list(ev_result.scalars().all())

    # Build report
    report = generate_eval_report(run, results, evaluators)

    # Generate LLM recommendations if there are failures
    if report["summary"]["failed"] > 0:
        try:
            llm = AnalysisLlmService(
                user_settings=dict(user.settings or {}), project_settings=project.settings
            )
            recommendations = await generate_recommendations(llm, report, db=db, project_id=project.id)
            report["recommendations"] = recommendations
        except Exception as e:
            logger.warning("Could not generate recommendations: %s", e)
            report["recommendations"] = []

    return report


# ── Rerun Endpoint (before /{run_id}) ─────────────────────────


@router.post(
    "/{run_id}/rerun",
    response_model=TriggerEvalResponse,
    status_code=202,
    dependencies=[require_write("evaluate", "evaluations")],
)
async def rerun_eval(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(get_current_project),
    user: User = Depends(get_current_user),
):
    """Rerun an evaluation using the same datasets as the original run."""
    # Find the original run
    result = await db.execute(
        select(EvalRun).where(EvalRun.id == run_id, EvalRun.project_id == project.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Eval run not found"}},
        )

    endpoint = _get_eval_endpoint(project)
    if not endpoint:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "NOT_CONFIGURED", "message": "Target API endpoint not configured. Set it in Settings → Evaluations."}},
        )

    # Find the original job to get dataset_ids and config
    dataset_ids: list[str] | None = None
    original_config: dict = {}
    job_result = await db.execute(
        select(EvalJob).where(EvalJob.run_id == run_id, EvalJob.project_id == project.id)
    )
    original_job = job_result.scalar_one_or_none()
    if original_job:
        if original_job.dataset_ids:
            dataset_ids = original_job.dataset_ids
        original_config = original_job.config or {}

    concurrency = original_config.get("concurrency", settings.eval_default_concurrency)
    filter_mode = original_config.get("filter_mode", "as_configured")
    max_turns = original_config.get("max_turns", 1)

    if dataset_ids:
        ds_result = await db.execute(
            select(TestDataset.name).where(TestDataset.id.in_(dataset_ids))
        )
        ds_names = [r[0] for r in ds_result.all()]
        dataset_label = ", ".join(ds_names) if ds_names else f"{len(dataset_ids)} dataset(s)"
    else:
        dataset_label = "all datasets"

    job = EvalJob(
        project_id=project.id,
        test_suite=dataset_label,
        dataset_ids=dataset_ids,
        status=EvalJobStatus.pending,
        config=original_config,
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)

    dataset_uuids = [UUID(d) for d in dataset_ids] if dataset_ids else None
    ps = dict(project.settings or {})
    ps["_user_settings"] = merge_llm_settings(project.settings, user.settings)
    task = asyncio.create_task(
        _run_eval_background(
            job.id,
            project.id,
            dataset_uuids,
            concurrency,
            ps,
            filter_mode=filter_mode,
            max_turns=max_turns,
        )
    )
    _eval_tasks[job.id] = task

    return TriggerEvalResponse(job_id=job.id, status="pending")
