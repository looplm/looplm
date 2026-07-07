"""Phase 1 helpers for the batch eval executor.

Extracted from `batch_eval_executor.py` to keep file sizes manageable.
These helpers run the target API + deterministic evaluators and collect
the LLM-judge prompts that will be submitted as a batch in Phase 2.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from app.models.models import (
    Evaluator,
    EvaluatorType,
    TestCase,
)
from app.schemas.evaluations import EvalResultImport, GraderResult
from app.services.eval_executor_helpers import (
    _SEVERITY,
    _build_result_metadata,
    _call_target_api_resilient,
    _fmt_ms,
    _with_elapsed_ms,
)
from app.services.eval_runners import (
    _run_deterministic,
    render_llm_judge_prompt,
)


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
    payload_key: str | None = None,
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
    execution: dict = {"status": "ok", "attempts": 0}

    async def _progress(msg: str):
        if on_progress:
            await on_progress(msg)

    for turn_num, turn in enumerate(turns, 1):
        turn_prompt = turn["prompt"]
        turn_expected = turn.get("expected_answer") or expected_output
        turn_prefix = f" turn {turn_num}/{len(turns)}:" if is_multi_turn else ""

        # Same resilient target call as the native path: process-wide concurrency cap,
        # retry+backoff, and keyword-fallback degrade detection (see model_resilience).
        await _progress(f"{turn_prefix} calling API...")
        outcome = await _call_target_api_resilient(
            client, endpoint, request_template, response_path,
            extra_headers, turn_prompt, test_case.context_filters,
            team_filter=team_filter,
            tag_filter=tag_filter,
            filter_enabled=filter_enabled,
            thread_id=thread_id,
            metadata=test_case.test_case_metadata,
            experiment_variables=experiment_variables,
            on_progress=lambda msg: _progress(f"{turn_prefix}{msg}"),
            allow_retry=thread_id is None,
        )
        execution["attempts"] += outcome.attempts
        if _SEVERITY[outcome.status] > _SEVERITY[execution["status"]]:
            execution["status"] = outcome.status
            if outcome.error:
                execution["error"] = outcome.error

        if outcome.status == "error":
            await _progress(f"{turn_prefix} API error: {outcome.error}")
            conversation_history.append({
                "turn": turn_num, "prompt": turn_prompt, "response": None,
                "pass": False, "error": outcome.error, "graders": {},
            })
            final_output = None
            final_raw_response = None
            final_graders = {}
            break

        if outcome.status == "degraded":
            # Soft failure: keep the response for display + DLQ retry, but don't grade it.
            await _progress(
                f"{turn_prefix} degraded retrieval ({outcome.retrieval_mode}); "
                "not graded, queued for retry"
            )
            conversation_history.append({
                "turn": turn_num, "prompt": turn_prompt,
                "response": (outcome.output_text or "")[:5000] or None,
                "pass": False, "degraded": True, "graders": {},
            })
            final_output = outcome.output_text
            final_raw_response = outcome.raw_response
            final_graders = {}
            break

        output_text = outcome.output_text
        raw_response = outcome.raw_response
        elapsed_ms = outcome.elapsed_ms

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

    metadata = _build_result_metadata(final_raw_response or "", payload_key=payload_key)
    if execution["status"] != "ok":
        metadata["execution"] = execution
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
