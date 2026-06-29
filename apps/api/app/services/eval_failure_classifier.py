"""Failure-pattern classification for eval runs.

Holds the semaphore + LLM + pattern-aggregation logic used by
``POST /api/evals/{run_id}/classify-failures``.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import EvalResult, EvalRun, Evaluator
from app.models.project import Project
from app.models.user import User
from app.schemas.evaluations import ClassifyFailuresResponse
from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService
from app.services.failure_pattern import aggregate_run_patterns, compute_failure_pattern

logger = logging.getLogger(__name__)


async def classify_run_failures(
    run: EvalRun,
    *,
    project: Project,
    user: User,
    db: AsyncSession,
) -> ClassifyFailuresResponse:
    """Compute or refresh ``failure_pattern`` for every failed result in a run.

    Idempotent: overwrites existing pattern fields on each failed result.
    Returns the updated run stats + ``failure_pattern_summary``.
    """
    failed_results = list((await db.execute(
        select(EvalResult).where(EvalResult.run_id == run.id, EvalResult.pass_ == False)  # noqa: E712
    )).scalars().all())

    if not failed_results:
        run.run_metadata = {
            **(run.run_metadata or {}),
            "failure_pattern_summary": {},
        }
        await db.commit()
        pass_rate = run.passed / run.total if run.total > 0 else 0.0
        return ClassifyFailuresResponse(
            total=run.total,
            passed=run.passed,
            failed=run.failed,
            pass_rate=pass_rate,
            classified=0,
            failure_pattern_summary={},
        )

    evaluators = list((await db.execute(
        select(Evaluator).where(Evaluator.project_id == project.id)
    )).scalars().all())
    affects_pass_map = {e.name: e.affects_pass for e in evaluators}

    llm: AnalysisLlmService | None
    try:
        llm = AnalysisLlmService(
            user_settings=dict(user.settings or {}), project_settings=project.settings
        )
    except AnalysisLlmConfigError as exc:
        logger.info("Classifying failures without LLM (config error: %s)", exc)
        llm = None

    sem = asyncio.Semaphore(8)

    async def _classify_one(result: EvalResult) -> str | None:
        async with sem:
            patch, _usage = await compute_failure_pattern(
                pass_=result.pass_,
                graders=result.graders,
                output=result.output,
                affects_pass_map=affects_pass_map,
                llm=llm,
            )
        if patch:
            result.result_metadata = {**(result.result_metadata or {}), **patch}
        return patch.get("failure_pattern")

    patterns = await asyncio.gather(*(_classify_one(r) for r in failed_results))

    summary = aggregate_run_patterns(patterns)
    run.run_metadata = {
        **(run.run_metadata or {}),
        "failure_pattern_summary": summary,
    }

    await db.commit()

    pass_rate = run.passed / run.total if run.total > 0 else 0.0
    return ClassifyFailuresResponse(
        total=run.total,
        passed=run.passed,
        failed=run.failed,
        pass_rate=pass_rate,
        classified=len(failed_results),
        failure_pattern_summary=summary,
    )
