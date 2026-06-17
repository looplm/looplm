"""Pure helper functions for evaluation endpoints."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from app.config import settings
from app.db import async_session
from app.models.models import EvalJob, EvalJobStatus
from app.models.project import Project
from app.schemas.evaluations import (
    EvalImportRequest,
    EvalResultImport,
    GraderResult,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.models import EvalRun

logger = logging.getLogger(__name__)

# Retrieval metrics rolled up from per-result grader details into run-level
# summaries. Each entry is (metric name, the key it's stored under in
# ``grader.details``); the summary field is ``f"{metric}_summary"`` and reuses the
# same details key for its at-k map (see ``_compute_summaries``).
_RETRIEVAL_METRICS: tuple[tuple[str, str], ...] = (
    ("recall", "recall_at_k"),
    ("precision", "precision_at_k"),
    ("hit_rate", "hit_rate_at_k"),
)


def _get_eval_endpoint(project: Project) -> str | None:
    """Return target API endpoint from project settings, falling back to env var."""
    project_settings = project.settings or {}
    return (
        project_settings.get("eval_target_endpoint")
        or settings.eval_target_endpoint
    )


def _compute_summaries(
    results: list[EvalResultImport] | list[dict],
) -> tuple[dict, dict]:
    """Compute grader_summary and score_summary from result list."""
    grader_counts: dict[str, dict] = {}
    score_accum: dict[str, list[float]] = {}
    # grader name -> metric ("recall"/"precision"/"hit_rate") -> k -> per-result
    # values, for the macro-average rollup of each retrieval metric.
    metric_accum: dict[str, dict[str, dict[str, list[float]]]] = {}

    for r in results:
        graders = r.graders if hasattr(r, "graders") else r.get("graders", {})
        scores = r.scores if hasattr(r, "scores") else r.get("scores", {})

        for name, g in graders.items():
            if name not in grader_counts:
                grader_counts[name] = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
            skipped = g.skipped if hasattr(g, "skipped") else g.get("skipped", False)
            passed = g.pass_ if hasattr(g, "pass_") else g.get("pass", False)
            grader_counts[name]["total"] += 1
            if skipped:
                grader_counts[name]["skipped"] += 1
            elif passed:
                grader_counts[name]["passed"] += 1
            else:
                grader_counts[name]["failed"] += 1

            details = g.details if hasattr(g, "details") else g.get("details")
            if isinstance(details, dict):
                for metric, details_key in _RETRIEVAL_METRICS:
                    at_k = details.get(details_key)
                    if not isinstance(at_k, dict):
                        continue
                    per_k = metric_accum.setdefault(name, {}).setdefault(metric, {})
                    for k, v in at_k.items():
                        try:
                            per_k.setdefault(k, []).append(float(v))
                        except (TypeError, ValueError):
                            continue

        for name, val in scores.items():
            if name not in score_accum:
                score_accum[name] = []
            score_accum[name].append(float(val))

    grader_summary = {}
    for name, c in grader_counts.items():
        evaluated = c["total"] - c["skipped"]
        grader_summary[name] = {
            "total": c["total"],
            "passed": c["passed"],
            "failed": c["failed"],
            "skipped": c["skipped"],
            "pass_rate": c["passed"] / evaluated if evaluated > 0 else 0.0,
        }
        for metric, details_key in _RETRIEVAL_METRICS:
            per_k = metric_accum.get(name, {}).get(metric)
            if per_k:
                grader_summary[name][f"{metric}_summary"] = {
                    "count": max(len(vals) for vals in per_k.values()),
                    details_key: {k: sum(vals) / len(vals) for k, vals in per_k.items()},
                }

    score_summary = {}
    for name, vals in score_accum.items():
        score_summary[name] = {
            "count": len(vals),
            "avg": sum(vals) / len(vals),
            "min": min(vals),
            "max": max(vals),
        }

    return grader_summary, score_summary


def _is_legacy_eval_import_format(raw: dict) -> bool:
    """Detect a legacy eval result file format kept for JSON import compatibility."""
    if "version" not in raw or "results" not in raw:
        return False
    results = raw["results"]
    if not results or not isinstance(results, list):
        return False
    first = results[0]
    return "id" in first and ("customGraders" in first or "actualAnswer" in first)


def _transform_legacy_eval_import(
    raw: dict,
    test_cases: list[dict] | None = None,
) -> EvalImportRequest:
    """Transform a legacy eval result JSON payload into the generic import schema."""
    tc_lookup: dict[str, dict] = {}
    if test_cases:
        for tc in test_cases:
            tc_lookup[tc.get("id", "")] = tc

    summary = raw.get("summary", {})
    name = raw.get("name") or f"Imported eval ({summary.get('total', '?')} tests)"
    timestamp = raw.get("timestamp", "")

    converted_results: list[EvalResultImport] = []
    for r in raw.get("results", []):
        test_id = r.get("id", "")
        tc = tc_lookup.get(test_id, {})

        graders: dict[str, GraderResult] = {}
        for gname, gval in r.get("customGraders", {}).items():
            graders[gname] = GraderResult(
                **{
                    "pass": gval.get("pass", False),
                    "reason": gval.get("reason"),
                    "skipped": gval.get("skipped", False),
                    "details": gval.get("details"),
                }
            )

        scores: dict[str, float] = {}
        for sname, sval in r.get("ragasScores", {}).items():
            if isinstance(sval, (int, float)):
                scores[sname] = float(sval)

        meta: dict[str, Any] = {}
        if r.get("toolsCalled"):
            meta["toolsCalled"] = r["toolsCalled"]

        converted_results.append(
            EvalResultImport(
                test_id=test_id,
                **{"pass": r.get("pass", False)},
                reason=r.get("reason"),
                input=tc.get("prompt"),
                output=r.get("actualAnswer"),
                expected_output=tc.get("expectedAnswer"),
                tags=tc.get("teamFilter", []),
                metadata=meta,
                graders=graders,
                scores=scores,
            )
        )

    return EvalImportRequest(
        name=name,
        source="legacy-eval-import",
        tags=[],
        metadata={"version": raw.get("version"), "timestamp": timestamp},
        results=converted_results,
    )


async def _import_eval_run_from_body(
    raw: dict,
    body: EvalImportRequest,
    project: Project,
    db: AsyncSession,
) -> tuple[EvalRun, int, int, dict, dict]:
    """Process an eval import request body and create the EvalRun + EvalResult records.

    Returns (run, total, passed, grader_summary, score_summary).
    """
    from app.models.models import EvalResult, EvalRun, JsonImport

    total = len(body.results)
    passed = sum(1 for r in body.results if r.pass_)
    failed = total - passed

    grader_summary, score_summary = _compute_summaries(body.results)

    run = EvalRun(
        project_id=project.id,
        name=body.name,
        source=body.source,
        tags=body.tags,
        total=total,
        passed=passed,
        failed=failed,
        grader_summary=grader_summary,
        score_summary=score_summary,
        run_metadata=body.metadata,
    )
    db.add(run)
    await db.flush()

    for r in body.results:
        graders_dict = {
            k: {"pass": v.pass_, "reason": v.reason, "skipped": v.skipped, "details": v.details}
            for k, v in r.graders.items()
        }
        result = EvalResult(
            run_id=run.id,
            test_id=r.test_id,
            pass_=r.pass_,
            reason=r.reason,
            input=r.input,
            output=r.output,
            expected_output=r.expected_output,
            tags=r.tags,
            graders=graders_dict,
            scores=r.scores,
            result_metadata=r.metadata,
            turns_to_pass=r.turns_to_pass,
        )
        db.add(result)

    # Record import history
    filename = raw.get("filename", "import.json") if isinstance(raw, dict) else "import.json"
    db.add(JsonImport(
        project_id=project.id,
        entity_type="evaluations",
        filename=filename,
        record_count=total,
    ))

    await db.flush()

    return run, total, passed, grader_summary, score_summary


async def _test_target_connection(
    body: dict,
    project: "Project",
) -> dict:
    """Test the target API connection with a sample prompt.

    Returns {"success": True, "response": ...} or {"success": False, "error": ...}.
    """
    import httpx

    from app.services.eval_runners import _call_target_api

    endpoint = body.get("endpoint") or (project.settings or {}).get("eval_target_endpoint")
    request_template = body.get("request_template") or (project.settings or {}).get("eval_request_template") or {"messages": [{"role": "user", "content": "{prompt}"}]}
    response_path = body.get("response_path") or (project.settings or {}).get("eval_response_path") or "choices.0.message.content"
    extra_headers = body.get("extra_headers") or (project.settings or {}).get("eval_extra_headers") or {}
    test_prompt = body.get("prompt", "Hello, this is a test.")

    if not endpoint:
        return {"success": False, "error": "No endpoint provided"}

    try:
        async with httpx.AsyncClient() as client:
            answer, _raw, elapsed_ms = await _call_target_api(
                client, endpoint, request_template, response_path,
                extra_headers, test_prompt,
            )
        return {"success": True, "response": answer[:500], "response_time_ms": elapsed_ms}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _recompute_stats_excluding(
    results: list,
    excluded: set[str],
    compute_summaries_fn,
) -> tuple[int, int, int, dict, dict]:
    """Recompute pass/fail stats excluding certain graders.

    Returns (total, passed, failed, grader_summary, score_summary).
    """
    passed = 0
    for r in results:
        result_pass = r.pass_
        graders = r.graders or {}
        for name, g in graders.items():
            if name in excluded:
                continue
            if g.get("skipped"):
                continue
            if not g.get("pass"):
                result_pass = False
                break
        if result_pass:
            passed += 1

    total = len(results)
    failed = total - passed

    # Recompute grader summary excluding the excluded ones
    grader_summary, score_summary = compute_summaries_fn(
        [{"graders": {k: v for k, v in (r.graders or {}).items() if k not in excluded}, "scores": r.scores or {}} for r in results]
    )

    return total, passed, failed, grader_summary, score_summary


async def _run_eval_background(
    job_id: UUID,
    project_id: UUID,
    dataset_ids: list[UUID] | None,
    concurrency: int,
    project_settings: dict | None = None,
    filter_mode: str = "as_configured",
    max_turns: int = 1,
    experiment_variables: dict[str, str] | None = None,
    session_id: UUID | None = None,
    experiment_id: UUID | None = None,
    experiment_name: str | None = None,
    use_batch: bool = False,
    include_test_ids: list[str] | None = None,
    rerun_of: UUID | None = None,
    rerun_scope: str | None = None,
    rerun_source_name: str | None = None,
) -> None:
    """Run eval in a background task with its own DB session."""
    import asyncio

    try:
        async with async_session() as db:
            if use_batch:
                # Subset reruns always run non-batch — the rerun endpoint forces
                # use_batch=False, so include_test_ids never reaches this branch.
                from app.services.batch_eval_executor import run_eval_batch
                await run_eval_batch(
                    job_id, project_id, dataset_ids, concurrency, db,
                    project_settings=project_settings,
                    filter_mode=filter_mode,
                    max_turns=max_turns,
                    experiment_variables=experiment_variables,
                    session_id=session_id,
                    experiment_id=experiment_id,
                    experiment_name=experiment_name,
                )
            else:
                from app.services.eval_executor import run_eval
                await run_eval(
                    job_id, project_id, dataset_ids, concurrency, db,
                    project_settings=project_settings,
                    filter_mode=filter_mode,
                    max_turns=max_turns,
                    experiment_variables=experiment_variables,
                    session_id=session_id,
                    experiment_id=experiment_id,
                    experiment_name=experiment_name,
                    include_test_ids=include_test_ids,
                    rerun_of=rerun_of,
                    rerun_scope=rerun_scope,
                    rerun_source_name=rerun_source_name,
                )
    except asyncio.CancelledError:
        logger.info("Background eval task cancelled for job %s", job_id)
        # Status already set to cancelled by the stop endpoint
    except Exception as e:
        logger.error("Background eval task failed for job %s: %s", job_id, e)
        try:
            async with async_session() as db:
                result = await db.execute(select(EvalJob).where(EvalJob.id == job_id))
                job = result.scalar_one_or_none()
                if job and job.status not in (EvalJobStatus.completed, EvalJobStatus.cancelled, EvalJobStatus.batch_pending):
                    job.status = EvalJobStatus.failed
                    job.error = str(e)[:2000]
                    await db.commit()
        except Exception:
            logger.error("Failed to update error status for eval job %s", job_id)
