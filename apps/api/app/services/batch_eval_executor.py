"""Batch eval executor — two-phase evaluation using Azure OpenAI Batch API.

Phase 1 (immediate): Call target API + run deterministic evaluators, collect
LLM judge prompts without calling them.

Phase 2 (async): Submit collected prompts as a batch job. A background poller
(batch_poller.py) processes results when the batch completes.
"""

from __future__ import annotations

import asyncio
import json
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
from app.schemas.evaluations import EvalResultImport, GraderResult
from app.services.analysis_llm import LlmUsageInfo
from app.services.batch_llm_service import BatchLlmService
from app.services.eval_executor_helpers import (
    _build_result_metadata,
    _fmt_ms,
    _with_elapsed_ms,
)
from app.services.eval_runners import (
    _call_target_api,
    _run_deterministic,
    render_llm_judge_prompt,
    parse_llm_judge_response,
)
from app.services.llm_pricing import calculate_cost

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 1 helpers
# ---------------------------------------------------------------------------


def _run_evaluators_collect_batch(
    evaluators: list[Evaluator],
    input_text: str,
    output_text: str,
    expected_output: str | None,
    raw_response: str,
    test_case: TestCase,
    elapsed_ms: int | None = None,
) -> tuple[dict[str, GraderResult], bool, dict[str, float], list[tuple[str, list[dict[str, str]]]]]:
    """Run deterministic evaluators and collect LLM judge prompts (no LLM calls).

    Returns (graders, overall_pass, scores, pending_llm_prompts).
    pending_llm_prompts is a list of (evaluator_name, messages) tuples.
    """
    graders: dict[str, GraderResult] = {}
    scores: dict[str, float] = {}
    overall_pass = True
    pending_llm: list[tuple[str, list[dict[str, str]]]] = []

    for evaluator in evaluators:
        if elapsed_ms is not None and (evaluator.config or {}).get("check_type") == "response_time":
            evaluator = _with_elapsed_ms(evaluator, elapsed_ms)

        if evaluator.type == EvaluatorType.deterministic:
            result = _run_deterministic(evaluator, output_text, test_case, context=raw_response)
            graders[evaluator.name] = GraderResult(
                **{"pass": result.get("pass", False), "reason": result.get("reason"), "skipped": result.get("skipped", False)}
            )
            if evaluator.affects_pass and not result.get("skipped") and not result.get("pass"):
                overall_pass = False

        elif evaluator.type == EvaluatorType.llm_judge:
            messages = render_llm_judge_prompt(evaluator, input_text, output_text, expected_output, context=raw_response)
            if messages is None:
                graders[evaluator.name] = GraderResult(**{"pass": False, "reason": "No prompt_template configured", "skipped": True})
            else:
                pending_llm.append((evaluator.name, messages))
                # Placeholder: will be updated when batch completes
                graders[evaluator.name] = GraderResult(
                    **{"pass": False, "reason": "Batch pending", "skipped": True}
                )

        else:
            # hybrid: run deterministic first, then collect LLM if needed
            result = _run_deterministic(evaluator, output_text, test_case, context=raw_response)
            if not result.get("skipped") and not result.get("pass"):
                messages = render_llm_judge_prompt(evaluator, input_text, output_text, expected_output, context=raw_response)
                if messages:
                    pending_llm.append((evaluator.name, messages))
                    graders[evaluator.name] = GraderResult(
                        **{"pass": False, "reason": "Batch pending", "skipped": True, "batch_pending": True}
                    )
                else:
                    graders[evaluator.name] = GraderResult(
                        **{"pass": result.get("pass", False), "reason": result.get("reason"), "skipped": result.get("skipped", False)}
                    )
                    if evaluator.affects_pass and not result.get("skipped") and not result.get("pass"):
                        overall_pass = False
            else:
                graders[evaluator.name] = GraderResult(
                    **{"pass": result.get("pass", False), "reason": result.get("reason"), "skipped": result.get("skipped", False)}
                )
                if evaluator.affects_pass and not result.get("skipped") and not result.get("pass"):
                    overall_pass = False

    if elapsed_ms is not None:
        scores["response_time_ms"] = float(elapsed_ms)

    if not any(e.affects_pass for e in evaluators):
        overall_pass = True

    return graders, overall_pass, scores, pending_llm


async def _evaluate_single_test_case_batch(
    client: httpx.AsyncClient,
    endpoint: str,
    request_template: dict,
    response_path: str,
    extra_headers: dict[str, str],
    evaluators: list[Evaluator],
    test_case: TestCase,
    filter_mode: str = "as_configured",
    max_turns: int = 1,
    on_progress=None,
    experiment_variables: dict[str, str] | None = None,
) -> tuple[EvalResultImport, list[tuple[str, list[dict[str, str]]]]]:
    """Evaluate a single test case: call target API + run deterministic evaluators.

    Returns (result, pending_llm_prompts) where pending_llm_prompts are
    the LLM judge calls to be batched.
    """
    input_text = test_case.prompt
    expected_output = test_case.expected_answer

    # Resolve filters
    if filter_mode == "no_filters":
        team_filter: list[str] | None = []
        tag_filter: list[str] | None = []
        filter_enabled = False
    else:
        team_filter = test_case.team_filter or []
        tag_filter = test_case.tag_filter or []
        filter_enabled = bool(team_filter or tag_filter)

    if experiment_variables:
        if "team_filter" in experiment_variables:
            team_filter = json.loads(experiment_variables["team_filter"])
            filter_enabled = bool(team_filter or tag_filter)
        if "tag_filter" in experiment_variables:
            tag_filter = json.loads(experiment_variables["tag_filter"])
            filter_enabled = bool(team_filter or tag_filter)
        if "filter_enabled" in experiment_variables:
            filter_enabled = json.loads(experiment_variables["filter_enabled"])

    # Only handle single turn for batch mode (multi-turn needs interactive LLM)
    turns = [{"prompt": input_text, "expected_answer": expected_output}]
    follow_ups = test_case.follow_up_prompts or []
    for fp in follow_ups:
        turns.append({
            "prompt": fp.get("prompt", ""),
            "expected_answer": fp.get("expected_answer") or fp.get("expectedAnswer"),
        })
    turns = turns[:max_turns]

    is_multi_turn = len(turns) > 1
    thread_id = str(asyncio.get_event_loop().time()) if is_multi_turn else None
    from uuid import uuid4
    thread_id = str(uuid4()) if is_multi_turn else None
    conversation_history: list[dict] = []

    final_output = None
    final_raw_response = None
    final_graders: dict[str, GraderResult] = {}
    final_scores: dict[str, float] = {}
    final_pass = False
    turns_to_pass: int | None = None
    all_pending_llm: list[tuple[str, list[dict[str, str]]]] = []

    async def _progress(msg: str):
        if on_progress:
            await on_progress(msg)

    for turn_num, turn in enumerate(turns, 1):
        turn_prompt = turn["prompt"]
        turn_expected = turn.get("expected_answer") or expected_output
        turn_prefix = f" turn {turn_num}/{len(turns)}:" if is_multi_turn else ""

        await _progress(f"{turn_prefix} calling API...")
        try:
            output_text, raw_response, elapsed_ms = await _call_target_api(
                client, endpoint, request_template, response_path,
                extra_headers, turn_prompt, test_case.context_filters,
                team_filter=team_filter,
                tag_filter=tag_filter,
                filter_enabled=filter_enabled,
                thread_id=thread_id,
                metadata=test_case.test_case_metadata,
                experiment_variables=experiment_variables,
            )
        except Exception as e:
            await _progress(f"{turn_prefix} API error: {e}")
            conversation_history.append({
                "turn": turn_num, "prompt": turn_prompt, "response": None,
                "pass": False, "error": str(e), "graders": {},
            })
            final_output = None
            final_raw_response = None
            final_graders = {}
            break

        await _progress(f"{turn_prefix} response received ({_fmt_ms(elapsed_ms)}), running deterministic graders...")

        graders, overall_pass, turn_scores, pending_llm = _run_evaluators_collect_batch(
            evaluators, turn_prompt, output_text, turn_expected, raw_response, test_case,
            elapsed_ms=elapsed_ms,
        )
        all_pending_llm.extend(pending_llm)

        graders_dict = {
            k: {"pass": v.pass_, "reason": v.reason, "skipped": v.skipped}
            for k, v in graders.items()
        }
        conversation_history.append({
            "turn": turn_num,
            "prompt": turn_prompt,
            "response": output_text[:5000] if output_text else None,
            "pass": overall_pass,
            "graders": graders_dict,
        })

        final_output = output_text
        final_raw_response = raw_response
        final_graders = graders
        final_scores = turn_scores
        final_pass = overall_pass

        # For batch mode, we don't know final pass until LLM judges run,
        # so we don't break early on pass
        if overall_pass and not pending_llm:
            turns_to_pass = turn_num
            break

    metadata = _build_result_metadata(final_raw_response or "")
    if is_multi_turn:
        metadata["conversation_history"] = conversation_history
    metadata["filter_mode"] = filter_mode
    if filter_enabled:
        metadata["team_filter"] = team_filter
        metadata["tag_filter"] = tag_filter
    if test_case.context_filters:
        metadata["context_filters"] = test_case.context_filters

    return EvalResultImport(
        test_id=test_case.test_id,
        **{"pass": final_pass},
        input=input_text,
        output=final_output,
        expected_output=expected_output,
        tags=test_case.tags or [],
        graders=final_graders,
        scores=final_scores,
        metadata=metadata,
        turns_to_pass=turns_to_pass,
    ), all_pending_llm


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
) -> None:
    """Execute a batch eval: Phase 1 runs immediately, Phase 2 submits Azure batch."""
    ps = project_settings or {}

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

        # Load test cases
        tc_query = select(TestCase).join(TestDataset)
        if dataset_ids:
            tc_query = tc_query.where(TestCase.dataset_id.in_(dataset_ids))
        tc_query = tc_query.where(TestDataset.project_id == project_id)
        tc_result = await db.execute(tc_query)
        test_cases = list(tc_result.scalars().all())

        if not test_cases:
            raise ValueError("No test cases found for the selected datasets.")

        _log(f"[Batch mode] Loaded {len(test_cases)} test cases (concurrency: {concurrency})")

        # Load evaluators
        ev_result = await db.execute(
            select(Evaluator).where(
                Evaluator.project_id == project_id,
                Evaluator.enabled == True,  # noqa: E712
            )
        )
        evaluators = list(ev_result.scalars().all())
        _log(f"Loaded {len(evaluators)} enabled evaluators")

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

    total = len(all_results)
    passed = sum(1 for r in all_results if r.pass_)
    run.total = total
    run.passed = passed
    run.failed = total - passed

    # Compute grader and score summaries from DB results
    grader_counts: dict[str, dict] = {}
    score_accum: dict[str, list[float]] = {}
    for r in all_results:
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
