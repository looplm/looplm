"""Helpers for the native eval executor — evaluator runners and single test case evaluation."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

import httpx

from app.models.models import Evaluator, EvaluatorType, TestCase
from app.schemas.evaluations import EvalResultImport, GraderResult
from app.services.analysis_llm import AnalysisLlmService, LlmUsageInfo
from app.services.model_resilience import (
    DEGRADED_RETRIEVAL_MODE,
    GLOBAL_TARGET_SEM,
    DegradedRetrievalError,
    retry_async,
)
from app.services.retrieval_config import (
    extract_retrieval_context_from_payload,
    extract_retrieved_chunks,
)
from app.services.eval_runners import (
    _call_target_api,
    _run_deterministic,
    _run_llm_judge,
)

logger = logging.getLogger(__name__)


def _with_elapsed_ms(evaluator: Evaluator, elapsed_ms: int) -> Evaluator:
    """Return a shallow copy of the evaluator with _elapsed_ms injected into config."""
    from copy import copy

    ev = copy(evaluator)
    ev.config = {**(ev.config or {}), "_elapsed_ms": elapsed_ms}
    return ev


def _safe_json_loads(raw: str) -> object:
    """Parse ``raw`` JSON, returning None instead of raising on malformed input."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _retrieval_mode_from_parsed(parsed: object) -> str | None:
    """Extract ``retrievalDiagnostics.retrievalMode`` from an already-parsed target response."""
    if isinstance(parsed, dict):
        diagnostics = parsed.get("retrievalDiagnostics")
        if isinstance(diagnostics, dict):
            mode = diagnostics.get("retrievalMode")
            if isinstance(mode, str) and mode:
                return mode
    return None


def _build_result_metadata(raw_response: str, *, payload_key: str | None = None) -> dict:
    """Build eval result metadata, extracting retrieval_context if present.

    ``payload_key`` is the project's configured retrieval payload key (from
    ``retrieval_source``); when None, common default keys are tried.
    """
    meta: dict = {"raw_response": raw_response}
    try:
        parsed = json.loads(raw_response)
    except (json.JSONDecodeError, TypeError):
        return meta

    ctx = extract_retrieval_context_from_payload(parsed, payload_key=payload_key)
    if ctx:
        meta["retrieval_context"] = ctx
    # Structured ranked chunks (with Azure chunk ids) for chunk-level relevance labeling.
    chunks = extract_retrieved_chunks(parsed, payload_key=payload_key)
    if chunks:
        meta["retrieved_chunks"] = chunks
    # Retrieval-path diagnostics from the target (rde-gpt exposes these on its eval
    # endpoint). ``retrievalMode == "keyword-fallback"`` means the target's vector
    # search failed for every query (e.g. its shared embeddings deployment throttled)
    # and it silently degraded to keyword-only retrieval — no vector, no reranker,
    # and its relevance filter becomes a no-op. Such a run is NOT representative of
    # prod, so surfacing the mode lets reviewers exclude it from quality comparisons.
    if isinstance(parsed, dict):
        diagnostics = parsed.get("retrievalDiagnostics")
        if isinstance(diagnostics, dict):
            meta["retrieval_diagnostics"] = diagnostics
        mode = _retrieval_mode_from_parsed(parsed)
        if mode:
            meta["retrieval_mode"] = mode
    return meta


async def _run_evaluators_for_turn(
    evaluators: list[Evaluator],
    llm: AnalysisLlmService | None,
    input_text: str,
    output_text: str,
    expected_output: str | None,
    raw_response: str,
    test_case: TestCase,
    elapsed_ms: int | None = None,
    payload_key: str | None = None,
) -> tuple[dict[str, GraderResult], bool, dict[str, float], list[LlmUsageInfo]]:
    """Run all evaluators for a single turn and return (graders, overall_pass, scores, llm_usages).

    Deterministic evaluators run immediately (sync). LLM-judge evaluators and
    hybrid evaluators that need an LLM fallback are gathered concurrently so
    that multiple judge calls don't block each other.
    """
    graders: dict[str, GraderResult] = {}
    scores: dict[str, float] = {}
    llm_usages: list[LlmUsageInfo] = []
    overall_pass = True

    # Phase 1: Run deterministic checks and identify LLM calls needed
    pending_llm: list[tuple[Evaluator, asyncio.Future[dict]]] = []

    for evaluator in evaluators:
        if elapsed_ms is not None and (evaluator.config or {}).get("check_type") == "response_time":
            evaluator = _with_elapsed_ms(evaluator, elapsed_ms)

        if evaluator.type == EvaluatorType.deterministic:
            result = _run_deterministic(
                evaluator, output_text, test_case, context=raw_response, payload_key=payload_key
            )
            graders[evaluator.name] = GraderResult(
                **{"pass": result.get("pass", False), "reason": result.get("reason"), "skipped": result.get("skipped", False), "details": result.get("details")}
            )
            if evaluator.affects_pass and not result.get("skipped") and not result.get("pass"):
                overall_pass = False

        elif evaluator.type == EvaluatorType.llm_judge:
            if llm is None:
                graders[evaluator.name] = GraderResult(**{"pass": False, "reason": "LLM not configured", "skipped": True})
            else:
                pending_llm.append((evaluator, _run_llm_judge(llm, evaluator, input_text, output_text, expected_output, context=raw_response)))

        else:
            # hybrid: run deterministic first, then LLM if needed
            result = _run_deterministic(
                evaluator, output_text, test_case, context=raw_response, payload_key=payload_key
            )
            if not result.get("skipped") and not result.get("pass") and llm:
                pending_llm.append((evaluator, _run_llm_judge(llm, evaluator, input_text, output_text, expected_output, context=raw_response)))
            else:
                graders[evaluator.name] = GraderResult(
                    **{"pass": result.get("pass", False), "reason": result.get("reason"), "skipped": result.get("skipped", False), "details": result.get("details")}
                )
                if evaluator.affects_pass and not result.get("skipped") and not result.get("pass"):
                    overall_pass = False

    # Phase 2: Run all LLM judge calls concurrently
    if pending_llm:
        llm_results = await asyncio.gather(*(coro for _, coro in pending_llm))
        for (evaluator, _), (result, usage) in zip(pending_llm, llm_results):
            graders[evaluator.name] = GraderResult(
                **{"pass": result.get("pass", False), "reason": result.get("reason"), "skipped": result.get("skipped", False)}
            )
            if usage is not None:
                llm_usages.append((evaluator.name, usage))
            if evaluator.affects_pass and not result.get("skipped") and not result.get("pass"):
                overall_pass = False

    # Record response time as a numeric score
    if elapsed_ms is not None:
        scores["response_time_ms"] = float(elapsed_ms)

    # If no evaluators affect pass, default to True (no judgment)
    if not any(e.affects_pass for e in evaluators):
        overall_pass = True

    return graders, overall_pass, scores, llm_usages


def _fmt_ms(ms: int) -> str:
    """Format milliseconds as seconds (if >= 1000) or milliseconds."""
    return f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms}ms"


@dataclass
class _TargetOutcome:
    """Result of a resilient target call, including its execution health.

    ``status`` is ``ok`` (usable, representative response), ``degraded`` (retries
    exhausted while the target stayed on keyword-only retrieval — response kept but
    flagged so it lands in the DLQ instead of being graded as representative), or
    ``error`` (hard failure after retries — no usable response).
    """

    output_text: str | None
    raw_response: str | None
    elapsed_ms: int
    status: str
    attempts: int
    retrieval_mode: str | None = None
    error: str | None = None


# Execution-status severity, used to escalate a multi-turn case to its worst turn.
_SEVERITY = {"ok": 0, "degraded": 1, "error": 2}


def execution_status_of(metadata: dict | None) -> str:
    """Execution health on a result's metadata: ``ok`` | ``degraded`` | ``error``.

    ``ok`` results carry no ``execution`` block (kept lean), so absence means ``ok``.
    Non-``ok`` results ran degraded or failed to run and must be excluded from a run's
    representative pass rate (they are the DLQ candidates).
    """
    return ((metadata or {}).get("execution") or {}).get("status", "ok")


async def _call_target_api_resilient(
    *args,
    on_progress: Callable[[str], Awaitable[None]] | None = None,
    allow_retry: bool = True,
    **kwargs,
) -> _TargetOutcome:
    """Call the target under retry+backoff and a process-wide concurrency ceiling.

    Retries real transient failures (429/5xx/timeout) and a detected
    ``keyword-fallback`` degrade (raised as :class:`DegradedRetrievalError` since it
    arrives as HTTP 200). Never raises: exhausted retries collapse into a
    ``degraded`` or ``error`` :class:`_TargetOutcome` so the caller records a soft
    failure rather than losing the row.

    ``allow_retry`` must be False for stateful (multi-turn) calls: retrying re-sends
    the same prompt to the same ``thread_id``, and the target already appended it on
    the first attempt, so a retry pollutes the conversation. Stateful calls run once.
    """
    attempts = 0
    max_attempts = None if allow_retry else 1

    async def _on_retry(attempt: int, delay: float, exc: BaseException) -> None:
        nonlocal attempts
        attempts = attempt
        if on_progress is not None:
            label = "degraded retrieval" if isinstance(exc, DegradedRetrievalError) else "transient error"
            await on_progress(f" {label}, retry {attempt} in {delay:.1f}s...")

    async def _once():
        async with GLOBAL_TARGET_SEM:
            output_text, raw_response, elapsed_ms = await _call_target_api(*args, **kwargs)
        mode = _retrieval_mode_from_parsed(_safe_json_loads(raw_response))
        if mode == DEGRADED_RETRIEVAL_MODE:
            raise DegradedRetrievalError(mode, payload=(output_text, raw_response, elapsed_ms))
        return output_text, raw_response, elapsed_ms, mode

    try:
        output_text, raw_response, elapsed_ms, mode = await retry_async(
            _once, max_attempts=max_attempts, on_retry=_on_retry
        )
        return _TargetOutcome(
            output_text, raw_response, elapsed_ms, "ok", attempts + 1, retrieval_mode=mode
        )
    except DegradedRetrievalError as exc:
        output_text, raw_response, elapsed_ms = exc.payload or (None, None, 0)
        return _TargetOutcome(
            output_text, raw_response, elapsed_ms, "degraded", attempts + 1, retrieval_mode=exc.mode
        )
    except Exception as exc:  # noqa: BLE001 — collapse hard failures into a soft ``error`` outcome
        return _TargetOutcome(None, None, 0, "error", attempts + 1, error=str(exc))


async def _evaluate_single_test_case(
    client: httpx.AsyncClient,
    endpoint: str,
    request_template: dict,
    response_path: str,
    extra_headers: dict[str, str],
    evaluators: list[Evaluator],
    llm: AnalysisLlmService | None,
    test_case: TestCase,
    filter_mode: str = "as_configured",
    max_turns: int = 1,
    on_progress: Callable[[str], Awaitable[None]] | None = None,
    experiment_variables: dict[str, str] | None = None,
    payload_key: str | None = None,
) -> tuple[EvalResultImport, list[LlmUsageInfo]]:
    """Run a single test case with optional multi-turn follow-ups.

    For multi-turn test cases, sends follow-up prompts to the same conversation
    thread (via thread_id) and grades after each turn. Stops early on first pass.
    """
    input_text = test_case.prompt
    expected_output = test_case.expected_answer

    # Resolve filters based on filter_mode
    if filter_mode == "no_filters":
        team_filter: list[str] | None = []
        tag_filter: list[str] | None = []
        filter_enabled = False
    else:
        team_filter = test_case.team_filter or []
        tag_filter = test_case.tag_filter or []
        filter_enabled = bool(team_filter or tag_filter)

    # Apply experiment variable overrides for known filter keys
    if experiment_variables:
        if "team_filter" in experiment_variables:
            team_filter = json.loads(experiment_variables["team_filter"])
            filter_enabled = bool(team_filter or tag_filter)
        if "tag_filter" in experiment_variables:
            tag_filter = json.loads(experiment_variables["tag_filter"])
            filter_enabled = bool(team_filter or tag_filter)
        if "filter_enabled" in experiment_variables:
            filter_enabled = json.loads(experiment_variables["filter_enabled"])

    # Build list of turns: initial prompt + follow-ups, capped at max_turns
    follow_ups = test_case.follow_up_prompts or []
    turns = [{"prompt": input_text, "expected_answer": expected_output}]
    for fp in follow_ups:
        turns.append({
            "prompt": fp.get("prompt", ""),
            "expected_answer": fp.get("expected_answer") or fp.get("expectedAnswer"),
        })
    turns = turns[:max_turns]

    is_multi_turn = len(turns) > 1
    thread_id = str(uuid4()) if is_multi_turn else None
    conversation_history: list[dict] = []

    # Track the last successful state for the final result
    final_output = None
    final_raw_response = None
    final_graders: dict[str, GraderResult] = {}
    final_scores: dict[str, float] = {}
    final_pass = False
    turns_to_pass: int | None = None
    all_llm_usages: list[LlmUsageInfo] = []
    # Execution health of the target calls (see _TargetOutcome). Escalates across
    # turns to the most severe status seen (error > degraded > ok).
    execution: dict = {"status": "ok", "attempts": 0}

    async def _progress(msg: str) -> None:
        if on_progress:
            await on_progress(msg)

    for turn_num, turn in enumerate(turns, 1):
        turn_prompt = turn["prompt"]
        turn_expected = turn.get("expected_answer") or expected_output
        turn_prefix = f" turn {turn_num}/{len(turns)}:" if is_multi_turn else ""

        # Call target API (retry+backoff, process-wide concurrency cap, degrade detection)
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
            # Multi-turn shares one thread_id; retrying would re-send the turn into a
            # stateful conversation, so stateful cases run once (fail-fast, no retry).
            allow_retry=thread_id is None,
        )
        execution["attempts"] += outcome.attempts
        if _SEVERITY[outcome.status] > _SEVERITY[execution["status"]]:
            execution["status"] = outcome.status
            if outcome.error:
                execution["error"] = outcome.error

        if outcome.status == "error":
            await _progress(f"{turn_prefix} API error: {outcome.error}")
            # Record failed API call in history and stop
            conversation_history.append({
                "turn": turn_num,
                "prompt": turn_prompt,
                "response": None,
                "pass": False,
                "error": outcome.error,
                "graders": {},
            })
            final_output = None
            final_raw_response = None
            final_graders = {}
            break

        if outcome.status == "degraded":
            # Soft failure: keep the (keyword-only) response for display + DLQ retry,
            # but do NOT grade it — a degraded path is not representative of prod, so
            # grading it would fold an infra artifact into the run's pass rate.
            await _progress(
                f"{turn_prefix} degraded retrieval ({outcome.retrieval_mode}); "
                "not graded, queued for retry"
            )
            conversation_history.append({
                "turn": turn_num,
                "prompt": turn_prompt,
                "response": (outcome.output_text or "")[:5000] or None,
                "pass": False,
                "degraded": True,
                "graders": {},
            })
            final_output = outcome.output_text
            final_raw_response = outcome.raw_response
            final_graders = {}
            break

        output_text = outcome.output_text
        raw_response = outcome.raw_response
        elapsed_ms = outcome.elapsed_ms

        await _progress(f"{turn_prefix} response received ({_fmt_ms(elapsed_ms)}), running {len(evaluators)} graders...")

        # Run evaluators for this turn
        graders, overall_pass, turn_scores, turn_usages = await _run_evaluators_for_turn(
            evaluators, llm, turn_prompt, output_text, turn_expected, raw_response, test_case,
            elapsed_ms=elapsed_ms,
            payload_key=payload_key,
        )
        all_llm_usages.extend(turn_usages)

        # Build serializable graders dict for history
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

        if overall_pass:
            turns_to_pass = turn_num
            break

    # Build result metadata
    metadata = _build_result_metadata(final_raw_response or "", payload_key=payload_key)
    metadata["dataset_id"] = str(test_case.dataset_id)
    # Execution health so the DLQ can distinguish "failed to run / degraded" from a
    # legitimate wrong-answer FAIL. ``ok`` results carry no flag (keeps rows lean).
    if execution["status"] != "ok":
        metadata["execution"] = execution
    if is_multi_turn:
        metadata["conversation_history"] = conversation_history

    # Persist resolved filter pre-conditions
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
    ), all_llm_usages
