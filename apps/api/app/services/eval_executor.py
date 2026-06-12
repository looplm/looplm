"""Native eval executor — runs evaluations directly from LoopLM DB.

Replaces the legacy CLI dependency. Loads test cases from datasets,
calls the target API via httpx, runs evaluators (LLM-judge + deterministic),
and writes EvalRun + EvalResult records.
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
from app.services.analysis_llm import AnalysisLlmService
from app.services.eval_executor_helpers import _evaluate_single_test_case
from app.services.retrieval_config import (
    extract_retrieval_context_from_payload,
    get_retrieval_payload_key_from_settings,
)
from app.services.failure_pattern import (
    aggregate_root_causes,
    aggregate_run_patterns,
    compute_failure_pattern,
    compute_root_cause,
)

logger = logging.getLogger(__name__)


async def run_eval(
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
    """Execute a native eval run: load test cases, call API, run evaluators, save results."""
    ps = project_settings or {}
    retrieval_payload_key = get_retrieval_payload_key_from_settings(ps)

    # Mark job as running
    result = await db.execute(select(EvalJob).where(EvalJob.id == job_id))
    job = result.scalar_one()
    job.status = EvalJobStatus.running
    await db.commit()

    log_lines: list[str] = []

    def _log(msg: str) -> None:
        log_lines.append(msg)
        logger.info("Job %s: %s", job_id, msg)

    try:
        # Resolve settings
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

        _log(f"Loaded {len(test_cases)} test cases (concurrency: {concurrency})")

        # Load enabled evaluators
        ev_result = await db.execute(
            select(Evaluator).where(
                Evaluator.project_id == project_id,
                Evaluator.enabled == True,  # noqa: E712
            )
        )
        evaluators = list(ev_result.scalars().all())
        _log(f"Loaded {len(evaluators)} enabled evaluators")
        affects_pass_map = {e.name: e.affects_pass for e in evaluators}

        # Initialize LLM service if needed
        llm: AnalysisLlmService | None = None
        has_llm_evaluators = any(
            e.type in (EvaluatorType.llm_judge, EvaluatorType.hybrid)
            for e in evaluators
        )
        if has_llm_evaluators:
            try:
                user_settings = ps.get("_user_settings")
                llm = AnalysisLlmService(user_settings=user_settings)
                _log(f"LLM service initialized (model: {llm.model})")
            except Exception as e:
                _log(f"Warning: LLM service unavailable ({e}), LLM-judge evaluators will be skipped")

        # Resolve filter_mode: experiment variables can override
        effective_filter_mode = filter_mode
        if experiment_variables and "filter_mode" in experiment_variables:
            effective_filter_mode = experiment_variables["filter_mode"]

        # Build run plan: in "both" mode, each test case runs twice
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

        # Build dataset name for the run
        if dataset_ids:
            ds_result = await db.execute(
                select(TestDataset.name).where(TestDataset.id.in_(dataset_ids))
            )
            ds_names = [row[0] for row in ds_result.all()]
            run_name = f"Eval: {', '.join(ds_names)}"
        else:
            run_name = "Eval: All datasets"

        if experiment_name:
            run_name += f" [{experiment_name}]"
        elif effective_filter_mode != "as_configured":
            run_name += f" ({effective_filter_mode})"

        # Create EvalRun early so intermediate results are visible
        run_meta = {
            "filter_mode": effective_filter_mode,
            "dataset_ids": [str(d) for d in dataset_ids] if dataset_ids else None,
            "max_turns": max_turns,
            "concurrency": concurrency,
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

        # Update progress and link job to run
        job.progress_total = len(run_plan)
        job.progress_current = 0
        job.run_id = run.id
        job.log = "\n".join(log_lines)
        await db.commit()
        await db.refresh(job)

        # Run test cases concurrently, saving results incrementally
        sem = asyncio.Semaphore(concurrency)
        db_lock = asyncio.Lock()
        eval_results: list[EvalResultImport] = []
        completed = 0
        passed_count = 0

        # Track which index each task occupies for progress logging
        task_index: dict[str, int] = {}
        next_index = 0

        async def _run_with_semaphore(tc: TestCase, fm: str) -> EvalResultImport:
            nonlocal completed, passed_count, next_index

            # Assign a stable index for this task's log prefix
            async with db_lock:
                next_index += 1
                idx = next_index
                task_key = f"{tc.test_id}:{fm}"
                task_index[task_key] = idx

            prefix = f"[{idx}/{len(run_plan)}] {tc.test_id}:"

            async def _on_progress(msg: str) -> None:
                async with db_lock:
                    _log(f"{prefix}{msg}")
                    job.log = "\n".join(log_lines)
                    try:
                        await db.commit()
                    except Exception:
                        await db.rollback()

            async with sem:
                r, llm_usages = await _evaluate_single_test_case(
                    client, endpoint, request_template, response_path,
                    extra_headers, evaluators, llm, tc, filter_mode=fm,
                    max_turns=max_turns,
                    on_progress=_on_progress,
                    experiment_variables=experiment_variables,
                    payload_key=retrieval_payload_key,
                )
                # In "both" mode, tag results so they can be distinguished
                if filter_mode == "both":
                    suffix = " [filtered]" if fm == "as_configured" else " [unfiltered]"
                    r = r.model_copy(update={"test_id": r.test_id + suffix})

                # Classify failure pattern (grader-derived + optional clarifying-question LLM check)
                if not r.pass_:
                    graders_for_pattern = {
                        k: {"pass": v.pass_, "skipped": v.skipped}
                        for k, v in r.graders.items()
                    }
                    pattern_patch, classifier_usage = await compute_failure_pattern(
                        pass_=r.pass_,
                        graders=graders_for_pattern,
                        output=r.output,
                        affects_pass_map=affects_pass_map,
                        llm=llm,
                    )
                    if pattern_patch:
                        r.metadata.update(pattern_patch)
                    if classifier_usage is not None:
                        llm_usages.append(("eval_pattern_classifier", classifier_usage))

                    # Attribute the failure to the retrieval or generation stage
                    retrieval_context = r.metadata.get("retrieval_context")
                    if not retrieval_context:
                        raw = r.metadata.get("raw_response")
                        if raw:
                            try:
                                parsed = json.loads(raw) if isinstance(raw, str) else raw
                            except (json.JSONDecodeError, TypeError):
                                parsed = None
                            retrieval_context = extract_retrieval_context_from_payload(
                                parsed, payload_key=retrieval_payload_key
                            )
                    root_cause_patch, root_cause_usage = await compute_root_cause(
                        pass_=r.pass_,
                        grader_pattern=pattern_patch.get("grader_pattern", []),
                        affects_pass_map=affects_pass_map,
                        question=r.input,
                        output=r.output,
                        expected=r.expected_output,
                        retrieval_context=retrieval_context,
                        llm=llm,
                    )
                    if root_cause_patch:
                        r.metadata.update(root_cause_patch)
                    if root_cause_usage is not None:
                        llm_usages.append(("eval_root_cause", root_cause_usage))

                # Serialize all DB operations — async sessions aren't concurrency-safe
                async with db_lock:
                    completed += 1
                    if r.pass_:
                        passed_count += 1
                    status = "PASS" if r.pass_ else "FAIL"
                    n_graders = len(r.graders)
                    n_failed = sum(1 for g in r.graders.values() if not g.skipped and not g.pass_)
                    n_skipped = sum(1 for g in r.graders.values() if g.skipped)
                    n_passed = n_graders - n_failed - n_skipped
                    turns_info = f" (turn {r.turns_to_pass})" if r.turns_to_pass and r.turns_to_pass > 1 else ""
                    grader_info = f" — {n_failed} failed / {n_skipped} skipped / {n_passed} passed" if n_graders else ""
                    _log(f"{prefix} {status}{turns_info}{grader_info}")

                    # Save result to DB immediately
                    graders_dict = {
                        k: {"pass": v.pass_, "reason": v.reason, "skipped": v.skipped, "details": v.details}
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

                    # Record LLM judge usage
                    if llm_usages:
                        from app.services.llm_usage_tracker import record_llm_usage
                        for evaluator_name, usage in llm_usages:
                            await record_llm_usage(
                                db,
                                project_id=project_id,
                                service_name="eval_judge",
                                function_name=evaluator_name,
                                provider=llm.provider if llm else "unknown",
                                model=llm.model if llm else "unknown",
                                usage=usage,
                            )

                    # Update progress and run stats
                    job.progress_current = completed
                    job.log = "\n".join(log_lines)
                    run.passed = passed_count
                    run.failed = completed - passed_count
                    try:
                        await db.commit()
                    except Exception as commit_err:
                        logger.error(
                            "Job %s: failed to commit result for %s: %s",
                            job_id, r.test_id, commit_err,
                        )
                        await db.rollback()
                        # Re-add the result so it's retried on the next commit
                        db.add(eval_result)

                return r

        async with httpx.AsyncClient() as client:
            tasks = [_run_with_semaphore(tc, fm) for tc, fm in run_plan]
            eval_results = await asyncio.gather(*tasks)

        # Final summaries
        total = len(eval_results)
        passed = sum(1 for r in eval_results if r.pass_)
        failed = total - passed
        grader_summary, score_summary = _compute_summaries(eval_results)

        run.total = total
        run.passed = passed
        run.failed = failed
        run.grader_summary = grader_summary
        run.score_summary = score_summary

        # Multi-turn summary stats
        multi_turn_passes = [r.turns_to_pass for r in eval_results if r.turns_to_pass is not None]
        multi_turn_tests = sum(1 for r in eval_results if r.metadata.get("conversation_history"))
        if multi_turn_passes:
            run.run_metadata = {
                **(run.run_metadata or {}),
                "avg_turns_to_pass": round(sum(multi_turn_passes) / len(multi_turn_passes), 2),
                "multi_turn_test_count": multi_turn_tests,
            }

        # Failure-pattern summary (counts of failure_pattern across failed results)
        failure_pattern_summary = aggregate_run_patterns(
            r.metadata.get("failure_pattern") for r in eval_results if not r.pass_
        )
        if failure_pattern_summary:
            run.run_metadata = {
                **(run.run_metadata or {}),
                "failure_pattern_summary": failure_pattern_summary,
            }

        # Root-cause summary (retrieval vs generation vs spec, across failed results)
        root_cause_summary = aggregate_root_causes(
            (r.metadata.get("root_cause") or {}).get("category")
            for r in eval_results if not r.pass_
        )
        if root_cause_summary:
            run.run_metadata = {
                **(run.run_metadata or {}),
                "root_cause_summary": root_cause_summary,
            }

        # Update job
        _log(f"Completed: {passed}/{total} passed ({passed/total*100:.0f}%)" if total else "Completed: 0 test cases")
        job.status = EvalJobStatus.completed
        job.completed_at = datetime.now(timezone.utc)
        job.log = "\n".join(log_lines)
        await db.commit()

        logger.info("Eval job %s completed: %d/%d passed", job_id, passed, total)

    except Exception as e:
        logger.error("Eval job %s failed: %s", job_id, e)
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
