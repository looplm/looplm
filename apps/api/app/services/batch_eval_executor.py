"""Batch eval executor — two-phase evaluation using Azure OpenAI Batch API.

Phase 1 (immediate): Call target API + run deterministic evaluators, collect
LLM judge prompts without calling them.

Phase 2 (async): Submit collected prompts as a batch job. A background poller
(batch_poller.py) processes results when the batch completes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import (
    BatchEvalJob,
    EvalJob,
    EvalJobStatus,
    EvalResult,
    EvalRun,
    Evaluator,
    EvaluatorType,
    TestCase,
    TestDataset,
)
from app.routers.eval_helpers import _compute_summaries
from app.schemas.evaluations import EvalResultImport
from app.services.batch_eval_helpers import _evaluate_single_test_case_batch
from app.services.retrieval_config import get_retrieval_payload_key_from_settings
from app.services.retrieval_metrics_aggregate import compute_and_store_run_retrieval_summary
from app.services.batch_llm_service import BatchLlmService
from app.services.batch_result_processor import process_batch_results  # re-export for batch_poller

__all__ = ["run_eval_batch", "process_batch_results"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_eval_batch(
    job_id: UUID,
    project_id: UUID,
    dataset_ids: list[UUID] | None,
    concurrency: int,
    db: AsyncSession,
    project_settings: dict | None = None,
    filter_mode: str = "as_configured",
    max_turns: int = 1,
    experiment_variables: dict[str, str] | None = None,
    session_id: UUID | None = None,
    experiment_id: UUID | None = None,
    experiment_name: str | None = None,
    retrieval_only: bool = False,
) -> None:
    """Execute a batch eval: Phase 1 runs immediately, Phase 2 submits Azure batch."""
    ps = project_settings or {}
    retrieval_payload_key = get_retrieval_payload_key_from_settings(ps)

    result = await db.execute(select(EvalJob).where(EvalJob.id == job_id))
    job = result.scalar_one()
    job.status = EvalJobStatus.running
    await db.commit()

    log_lines: list[str] = []

    def _log(msg: str):
        log_lines.append(msg)
        logger.info("Job %s: %s", job_id, msg)

    try:
        # Resolve settings (same as run_eval)
        endpoint = ps.get("eval_target_endpoint") or settings.eval_target_endpoint
        if not endpoint:
            raise ValueError("Target API endpoint not configured. Set it in Settings → Evaluations.")

        request_template = ps.get("eval_request_template") or {"messages": [{"role": "user", "content": "{prompt}"}]}
        response_path = ps.get("eval_response_path") or "choices.0.message.content"
        extra_headers = ps.get("eval_extra_headers") or {}

        # Load test cases (cases marked needs_work are excluded from runs)
        tc_query = select(TestCase).join(TestDataset).where(TestCase.status != "needs_work")
        if dataset_ids:
            tc_query = tc_query.where(TestCase.dataset_id.in_(dataset_ids))
        tc_query = tc_query.where(TestDataset.project_id == project_id)
        tc_result = await db.execute(tc_query)
        test_cases = list(tc_result.scalars().all())

        if not test_cases:
            raise ValueError("No test cases found for the selected datasets.")

        _log(f"[Batch mode] Loaded {len(test_cases)} test cases (concurrency: {concurrency})")

        # Load evaluators (retrieval-only runs skip generation evaluators)
        ev_filter = [
            Evaluator.project_id == project_id,
            Evaluator.enabled == True,  # noqa: E712
        ]
        if retrieval_only:
            ev_filter.append(Evaluator.category == "retrieval")
        ev_result = await db.execute(select(Evaluator).where(*ev_filter))
        evaluators = list(ev_result.scalars().all())
        _log(
            f"Loaded {len(evaluators)} enabled evaluators"
            + (" (retrieval only)" if retrieval_only else "")
        )

        has_llm_evaluators = any(
            e.type in (EvaluatorType.llm_judge, EvaluatorType.hybrid) for e in evaluators
        )
        if not has_llm_evaluators:
            _log("No LLM evaluators found — batch mode not needed, run a normal eval instead")
            raise ValueError("Batch mode requires at least one LLM-judge or hybrid evaluator.")

        # Initialize batch LLM service
        user_settings = ps.get("_user_settings")
        batch_service = BatchLlmService(user_settings=user_settings)
        _log(f"Batch LLM service initialized (model: {batch_service.model})")

        # Resolve filter mode
        effective_filter_mode = filter_mode
        if experiment_variables and "filter_mode" in experiment_variables:
            effective_filter_mode = experiment_variables["filter_mode"]

        # Build run plan
        if effective_filter_mode == "both":
            run_plan: list[tuple[TestCase, str]] = []
            for tc in test_cases:
                has_filters = bool(tc.team_filter or tc.tag_filter)
                if has_filters:
                    run_plan.append((tc, "as_configured"))
                    run_plan.append((tc, "no_filters"))
                else:
                    run_plan.append((tc, "no_filters"))
            _log(f"Filter mode 'both': {len(run_plan)} runs from {len(test_cases)} test cases")
        else:
            run_plan = [(tc, effective_filter_mode) for tc in test_cases]

        if effective_filter_mode != "as_configured":
            _log(f"Filter mode: {effective_filter_mode}")
        if experiment_variables:
            _log(f"Experiment variables: {experiment_variables}")

        # Build run name
        if dataset_ids:
            ds_result = await db.execute(
                select(TestDataset.name).where(TestDataset.id.in_(dataset_ids))
            )
            ds_names = [row[0] for row in ds_result.all()]
            run_name = f"Eval (batch): {', '.join(ds_names)}"
        else:
            run_name = "Eval (batch): All datasets"

        if experiment_name:
            run_name += f" [{experiment_name}]"
        elif effective_filter_mode != "as_configured":
            run_name += f" ({effective_filter_mode})"

        # Create EvalRun
        run_meta = {
            "filter_mode": effective_filter_mode,
            "dataset_ids": [str(d) for d in dataset_ids] if dataset_ids else None,
            "max_turns": max_turns,
            "concurrency": concurrency,
            "batch_mode": True,
        }
        if session_id:
            run_meta["session_id"] = str(session_id)
        if experiment_id:
            run_meta["experiment_id"] = str(experiment_id)
        if experiment_variables:
            run_meta["experiment_variables"] = experiment_variables
        if experiment_name:
            run_meta["experiment_name"] = experiment_name

        run = EvalRun(
            project_id=project_id,
            name=run_name,
            source="triggered",
            tags=[],
            total=len(run_plan),
            passed=0,
            failed=0,
            grader_summary={},
            score_summary={},
            run_metadata=run_meta,
            session_id=session_id,
            experiment_id=experiment_id,
        )
        db.add(run)
        await db.flush()

        job.progress_total = len(run_plan)
        job.progress_current = 0
        job.run_id = run.id
        job.log = "\n".join(log_lines)
        await db.commit()
        await db.refresh(job)

        # ---------------------------------------------------------------
        # Phase 1: Run target API + deterministic evaluators
        # ---------------------------------------------------------------
        _log("Phase 1: Running target API calls and deterministic evaluators...")
        sem = asyncio.Semaphore(concurrency)
        db_lock = asyncio.Lock()
        eval_results: list[EvalResultImport] = []
        # Maps eval_result DB id → list of (evaluator_name, messages)
        all_batch_prompts: list[tuple[UUID, str, list[dict[str, str]]]] = []
        completed = 0
        passed_count = 0
        next_index = 0

        async def _run_with_semaphore(tc: TestCase, fm: str) -> EvalResultImport:
            nonlocal completed, passed_count, next_index

            async with db_lock:
                next_index += 1
                idx = next_index

            prefix = f"[{idx}/{len(run_plan)}] {tc.test_id}:"

            async def _on_progress(msg: str):
                async with db_lock:
                    _log(f"{prefix}{msg}")
                    job.log = "\n".join(log_lines)
                    try:
                        await db.commit()
                    except Exception:
                        await db.rollback()

            async with sem:
                r, pending_llm = await _evaluate_single_test_case_batch(
                    client, endpoint, request_template, response_path,
                    extra_headers, evaluators, tc, filter_mode=fm,
                    max_turns=max_turns,
                    on_progress=_on_progress,
                    experiment_variables=experiment_variables,
                    payload_key=retrieval_payload_key,
                )
                if filter_mode == "both":
                    suffix = " [filtered]" if fm == "as_configured" else " [unfiltered]"
                    r = r.model_copy(update={"test_id": r.test_id + suffix})

                async with db_lock:
                    completed += 1
                    if r.pass_:
                        passed_count += 1

                    n_pending = len(pending_llm)
                    status = "PARTIAL" if n_pending > 0 else ("PASS" if r.pass_ else "FAIL")
                    _log(f"{prefix} {status} ({n_pending} LLM judges pending)")

                    # Track which evaluators have pending batch prompts
                    pending_evaluator_names = {name for name, _ in pending_llm}
                    graders_dict = {
                        k: {"pass": v.pass_, "reason": v.reason, "skipped": v.skipped,
                            **({"batch_pending": True} if k in pending_evaluator_names else {})}
                        for k, v in r.graders.items()
                    }
                    eval_result = EvalResult(
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
                        result_metadata=r.metadata or {},
                        turns_to_pass=r.turns_to_pass,
                    )
                    db.add(eval_result)
                    await db.flush()

                    # Track pending LLM prompts with the result's DB id
                    for evaluator_name, messages in pending_llm:
                        all_batch_prompts.append((eval_result.id, evaluator_name, messages))

                    job.progress_current = completed
                    job.log = "\n".join(log_lines)
                    run.passed = passed_count
                    run.failed = completed - passed_count
                    try:
                        await db.commit()
                    except Exception:
                        await db.rollback()

                return r

        async with httpx.AsyncClient() as client:
            tasks = [_run_with_semaphore(tc, fm) for tc, fm in run_plan]
            eval_results = await asyncio.gather(*tasks)

        _log(f"Phase 1 complete: {len(eval_results)} test cases, {len(all_batch_prompts)} LLM judge calls pending")

        # ---------------------------------------------------------------
        # Phase 2: Submit batch job
        # ---------------------------------------------------------------
        if not all_batch_prompts:
            # No LLM judges needed — complete immediately
            _log("No LLM judge calls needed, completing immediately")
            total = len(eval_results)
            passed = sum(1 for r in eval_results if r.pass_)
            grader_summary, score_summary = _compute_summaries(eval_results)
            run.total = total
            run.passed = passed
            run.failed = total - passed
            run.grader_summary = grader_summary
            run.score_summary = score_summary
            await compute_and_store_run_retrieval_summary(db, run, project_id)
            job.status = EvalJobStatus.completed
            job.completed_at = datetime.now(timezone.utc)
            job.log = "\n".join(log_lines)
            await db.commit()
            return

        _log(f"Phase 2: Submitting {len(all_batch_prompts)} LLM judge calls as batch...")

        # Build batch requests
        request_mapping: dict[str, dict] = {}
        batch_requests = []
        for result_id, evaluator_name, messages in all_batch_prompts:
            custom_id = f"{result_id}:{evaluator_name}"
            batch_requests.append(batch_service.build_batch_request(custom_id, messages))
            request_mapping[custom_id] = {
                "result_id": str(result_id),
                "evaluator_name": evaluator_name,
            }

        # Submit batch
        batch_id, input_file_id = await batch_service.submit_batch(batch_requests)
        _log(f"Batch submitted: {batch_id} ({len(batch_requests)} requests)")

        # Create BatchEvalJob record
        batch_eval_job = BatchEvalJob(
            eval_job_id=job_id,
            run_id=run.id,
            project_id=project_id,
            batch_id=batch_id,
            input_file_id=input_file_id,
            status="submitted",
            total_requests=len(batch_requests),
            request_mapping=request_mapping,
            submitted_at=datetime.now(timezone.utc),
        )
        db.add(batch_eval_job)
        await db.flush()

        # Link batch job to eval job
        job.batch_eval_job_id = batch_eval_job.id
        job.status = EvalJobStatus.batch_pending
        job.log = "\n".join(log_lines)
        await db.commit()

        _log("Batch job created, waiting for results (up to 24h)...")

    except Exception as e:
        logger.error("Batch eval job %s failed: %s", job_id, e)
        try:
            await db.rollback()
            result = await db.execute(select(EvalJob).where(EvalJob.id == job_id))
            job = result.scalar_one()
            job.status = EvalJobStatus.failed
            job.error = str(e)[:2000]
            job.completed_at = datetime.now(timezone.utc)
            log_lines.append(f"ERROR: {e}")
            job.log = "\n".join(log_lines)
            await db.commit()
        except Exception:
            logger.error("Failed to update job %s error status", job_id)
