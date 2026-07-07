"""Batch result processing for the batch eval executor.

Extracted from `batch_eval_executor.py`. Called by `batch_poller` once an
Azure OpenAI Batch job completes — downloads the results, updates each
EvalResult's grader entries, and recomputes the run/job summaries.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    BatchEvalJob,
    EvalJob,
    EvalJobStatus,
    EvalResult,
    EvalRun,
    Evaluator,
)
from app.services.analysis_llm import LlmUsageInfo
from app.services.batch_llm_service import BatchLlmService
from app.services.eval_executor_helpers import execution_status_of
from app.services.eval_runners import parse_llm_judge_response
from app.services.llm_pricing import calculate_cost

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result processing (called by batch_poller when batch completes)
# ---------------------------------------------------------------------------


async def process_batch_results(
    batch_eval_job: BatchEvalJob,
    db: AsyncSession,
) -> None:
    """Process completed batch results: update EvalResults, recompute summaries."""
    batch_service = BatchLlmService()  # uses default settings

    # Download results
    status_info = await batch_service.check_status(batch_eval_job.batch_id)
    output_file_id = status_info.get("output_file_id")
    if not output_file_id:
        raise ValueError(f"Batch {batch_eval_job.batch_id} has no output file")

    results = await batch_service.download_results(output_file_id)
    logger.info("Downloaded %d batch results for batch %s", len(results), batch_eval_job.batch_id)

    request_mapping = batch_eval_job.request_mapping or {}

    # Process each result
    updated_result_ids: set[UUID] = set()
    for batch_result in results:
        custom_id = batch_result.get("custom_id", "")
        mapping = request_mapping.get(custom_id)
        if not mapping:
            logger.warning("Unknown custom_id in batch results: %s", custom_id)
            continue

        result_id = UUID(mapping["result_id"])
        evaluator_name = mapping["evaluator_name"]
        updated_result_ids.add(result_id)

        # Load eval result
        er_result = await db.execute(select(EvalResult).where(EvalResult.id == result_id))
        eval_result = er_result.scalar_one_or_none()
        if not eval_result:
            logger.warning("EvalResult %s not found for batch custom_id %s", result_id, custom_id)
            continue

        # Parse the batch response
        response_body = batch_result.get("response", {}).get("body", {})
        status_code = batch_result.get("response", {}).get("status_code", 500)

        if status_code == 200 and response_body.get("choices"):
            content = response_body["choices"][0].get("message", {}).get("content", "")
            grader_result = parse_llm_judge_response(content)
        else:
            error_msg = batch_result.get("error", {}).get("message", "Unknown batch error")
            grader_result = {"pass": False, "reason": f"Batch request failed: {error_msg}", "skipped": True}

        # Update the grader in the eval result
        graders = dict(eval_result.graders or {})
        graders[evaluator_name] = {
            "pass": grader_result["pass"],
            "reason": grader_result["reason"],
            "skipped": grader_result.get("skipped", False),
        }
        eval_result.graders = graders

        # Record LLM usage from batch result
        usage_data = response_body.get("usage")
        if usage_data:
            input_tokens = usage_data.get("prompt_tokens", 0)
            output_tokens = usage_data.get("completion_tokens", 0)
            total_tokens = usage_data.get("total_tokens", 0)
            cost_model = response_body.get("model", batch_service.model)
            cost = calculate_cost(cost_model, input_tokens, output_tokens)

            usage_info = LlmUsageInfo(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=cost * 0.5 if cost else None,  # batch pricing is 50% of standard
                cached_tokens=0,
                reasoning_tokens=0,
                duration_ms=0,
            )
            from app.services.llm_usage_tracker import record_llm_usage
            await record_llm_usage(
                db,
                project_id=batch_eval_job.project_id,
                service_name="eval_judge_batch",
                function_name=evaluator_name,
                provider=batch_service.provider,
                model=batch_service.model,
                usage=usage_info,
            )

    # Recompute pass/fail for each updated eval result
    for result_id in updated_result_ids:
        er_result = await db.execute(select(EvalResult).where(EvalResult.id == result_id))
        eval_result = er_result.scalar_one_or_none()
        if not eval_result:
            continue

        # Load evaluators to check affects_pass
        ev_result = await db.execute(
            select(Evaluator).where(Evaluator.project_id == batch_eval_job.project_id)
        )
        evaluators_by_name = {e.name: e for e in ev_result.scalars().all()}

        overall_pass = True
        graders = eval_result.graders or {}
        for name, grader in graders.items():
            ev = evaluators_by_name.get(name)
            if ev and ev.affects_pass and not grader.get("skipped") and not grader.get("pass"):
                overall_pass = False
                break

        if not any(e.affects_pass for e in evaluators_by_name.values() if e.name in graders):
            overall_pass = True

        eval_result.pass_ = overall_pass

    await db.flush()

    # Recompute run summaries
    run_result = await db.execute(select(EvalRun).where(EvalRun.id == batch_eval_job.run_id))
    run = run_result.scalar_one()

    all_results_q = await db.execute(
        select(EvalResult).where(EvalResult.run_id == run.id)
    )
    all_results = list(all_results_q.scalars().all())

    # Exclude degraded/errored rows from the headline stats and grader summaries — they
    # did not run against a representative target path (see execution_status_of). They
    # persist as rows for the DLQ and are counted separately.
    representative = [r for r in all_results if execution_status_of(r.result_metadata) == "ok"]
    degraded_count = sum(1 for r in all_results if execution_status_of(r.result_metadata) == "degraded")
    error_count = sum(1 for r in all_results if execution_status_of(r.result_metadata) == "error")
    total = len(representative)
    passed = sum(1 for r in representative if r.pass_)
    run.total = total
    run.passed = passed
    run.failed = total - passed
    if degraded_count or error_count:
        run.run_metadata = {
            **(run.run_metadata or {}),
            "execution_counts": {"ok": total, "degraded": degraded_count, "error": error_count},
        }

    # Compute grader and score summaries from DB results
    grader_counts: dict[str, dict] = {}
    score_accum: dict[str, list[float]] = {}
    for r in representative:
        for name, grader in (r.graders or {}).items():
            if name not in grader_counts:
                grader_counts[name] = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
            grader_counts[name]["total"] += 1
            if grader.get("skipped"):
                grader_counts[name]["skipped"] += 1
            elif grader.get("pass"):
                grader_counts[name]["passed"] += 1
            else:
                grader_counts[name]["failed"] += 1
        for name, score in (r.scores or {}).items():
            if name not in score_accum:
                score_accum[name] = []
            score_accum[name].append(float(score))

    run.grader_summary = grader_counts
    run.score_summary = {
        name: {
            "mean": round(sum(vals) / len(vals), 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "count": len(vals),
        }
        for name, vals in score_accum.items()
        if vals
    }

    # Retrieval-quality snapshot for the finished batch run (URLs path).
    from app.services.retrieval_metrics_aggregate import compute_and_store_run_retrieval_summary

    await compute_and_store_run_retrieval_summary(db, run, batch_eval_job.project_id)

    # Update eval job
    job_result = await db.execute(select(EvalJob).where(EvalJob.id == batch_eval_job.eval_job_id))
    job = job_result.scalar_one()
    job.status = EvalJobStatus.completed
    job.completed_at = datetime.now(timezone.utc)

    # Append completion log
    existing_log = job.log or ""
    completion_msg = f"Batch completed: {passed}/{total} passed ({passed/total*100:.0f}%)" if total else "Batch completed: 0 test cases"
    job.log = existing_log + "\n" + completion_msg

    # Update batch eval job
    batch_eval_job.status = "completed"
    batch_eval_job.completed_requests = status_info.get("completed", 0)
    batch_eval_job.failed_requests = status_info.get("failed", 0)
    batch_eval_job.completed_at = datetime.now(timezone.utc)

    await db.commit()
    logger.info("Batch eval job %s completed: %d/%d passed", batch_eval_job.id, passed, total)
