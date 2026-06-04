"""Failure-pattern classification for eval results.

Layers:
- ``derive_grader_pattern``: deterministic — which ``affects_pass`` graders failed.
- ``classify_assistant_intent``: one short LLM call — flags clarifying questions.
- ``compute_failure_pattern``: combines both into a stable ``failure_pattern`` label.
- ``compute_root_cause``: attributes a failure to the retrieval or generation
  stage (deterministic-first, one LLM call only when graders can't decide).

Storage shape (lives on ``EvalResult.result_metadata`` JSONB):
- ``failure_pattern``: short label, e.g. ``"faithfulness"`` or ``"needs_more_info"``.
- ``grader_pattern``: sorted list of affects-pass graders that failed.
- ``assistant_intent`` (optional): one of {clarifying_question, refusal, other}.
- ``root_cause`` (optional): {category, confidence, source, evidence, missing_facts}.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any, Literal

from app.services.analysis_llm import AnalysisLlmService, LlmUsageInfo

logger = logging.getLogger(__name__)

Intent = Literal["answer", "clarifying_question", "refusal", "other"]
_INTENT_VALUES: tuple[str, ...] = ("answer", "clarifying_question", "refusal", "other")

NEEDS_MORE_INFO = "needs_more_info"
UNKNOWN = "unknown"

RootCause = Literal["retrieval", "generation", "task_spec", "indeterminate"]

# Evaluator names that signal *which stage* failed (see
# routers/evaluator_helpers.py::known_evaluators). Compared after ``_norm`` so
# both camelCase (``sourceRetrieval``) and snake_case (``source_retrieval``) match.
_RETRIEVAL_GRADERS = {"sourceretrieval"}
_GENERATION_GRADERS = {"faithfulness", "factualcorrectness", "faithfulnesstosource"}


def _norm(name: str) -> str:
    """Normalise an evaluator name for matching: strip separators, lowercase."""
    return name.replace("_", "").replace("-", "").replace(" ", "").lower()

_SUFFICIENCY_VALUES: tuple[str, ...] = ("sufficient", "partial", "insufficient")

_SUFFICIENCY_SYSTEM = (
    "You judge whether retrieved context was good enough to answer a question. "
    "Look ONLY at the question, the retrieved context, and (if given) the "
    "expected answer — IGNORE whatever answer the assistant actually produced. "
    'Return ONLY a JSON object: {"sufficiency": "<value>", "missing_facts": [..]}.'
    "\n\n"
    '- "sufficient": the context contains everything needed to produce a correct '
    "answer.\n"
    '- "partial": the context contains some but not all of the needed information.\n'
    '- "insufficient": the context lacks the information needed to answer.\n'
    "\n"
    '"missing_facts" is a short list of specific facts the context is missing '
    "(empty when sufficient). Default to \"sufficient\" only when the context "
    "clearly supports the expected answer; otherwise lean toward partial."
)

# Keep judge inputs bounded to control token cost.
_CONTEXT_MAX_CHARS = 8000

_CLASSIFIER_SYSTEM = (
    "You classify what an assistant did in its reply for an LLM evaluation. "
    'Return ONLY a JSON object of the form {"intent": "<value>"}, no prose.\n'
    "\n"
    "Pick the value that describes the reply *as a whole*:\n"
    '- "clarifying_question": the assistant did NOT answer the user. '
    "Instead, the entire reply is a question (or set of questions) asking "
    "the user for missing information needed to answer.\n"
    '- "refusal": the assistant declined or said it could not / would not '
    "answer.\n"
    '- "answer": the assistant attempted to answer the user. Still pick '
    '"answer" if the reply gives substantive content and only ends with a '
    "follow-up question, a check-in, or an offer to help further — those "
    "are not clarifying questions.\n"
    '- "other": none of the above fits.\n'
    "\n"
    'Default to "answer" when uncertain. Only use "clarifying_question" if '
    "the reply contains no substantive answer at all."
)

# Keep the classifier prompt short to minimise token cost.
_OUTPUT_MAX_CHARS = 3000


def derive_grader_pattern(
    graders: dict[str, Any] | None,
    affects_pass_map: dict[str, bool],
) -> list[str]:
    """Return sorted list of ``affects_pass`` graders that failed and weren't skipped."""
    failed: list[str] = []
    for name, g in (graders or {}).items():
        if not isinstance(g, dict):
            continue
        if not affects_pass_map.get(name):
            continue
        if g.get("skipped"):
            continue
        if g.get("pass"):
            continue
        failed.append(name)
    return sorted(failed)


async def classify_assistant_intent(
    output: str | None,
    llm: AnalysisLlmService,
) -> tuple[Intent, LlmUsageInfo | None]:
    """Classify the assistant's reply via a single short LLM call.

    Falls back to ``("answer", None)`` on empty output or any error — the
    caller treats that as 'no clarifying-question pattern detected'.
    """
    text = (output or "").strip()
    if not text:
        return "answer", None

    truncated = text[:_OUTPUT_MAX_CHARS]
    try:
        content, usage = await llm.tracked_chat_completion(
            messages=[
                {"role": "system", "content": _CLASSIFIER_SYSTEM},
                {"role": "user", "content": f"Assistant reply:\n\n{truncated}"},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning("Failure-pattern classifier call failed: %s", exc)
        return "answer", None

    try:
        parsed = json.loads(content)
        intent = parsed.get("intent")
        if intent in _INTENT_VALUES:
            return intent, usage  # type: ignore[return-value]
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return "answer", usage


async def compute_failure_pattern(
    *,
    pass_: bool,
    graders: dict[str, Any] | None,
    output: str | None,
    affects_pass_map: dict[str, bool],
    llm: AnalysisLlmService | None,
) -> tuple[dict[str, Any], LlmUsageInfo | None]:
    """Compute a failure-pattern patch to merge into ``EvalResult.result_metadata``.

    Returns ``(patch, usage)``. ``patch`` is empty for passed tests; for failed
    tests it always contains ``failure_pattern`` and ``grader_pattern``, and may
    include ``assistant_intent``. ``usage`` is the LLM usage from the intent
    classifier (None if it wasn't called).
    """
    if pass_:
        return {}, None

    grader_pattern = derive_grader_pattern(graders, affects_pass_map)

    intent: Intent = "answer"
    usage: LlmUsageInfo | None = None
    if llm is not None and output:
        intent, usage = await classify_assistant_intent(output, llm)

    patch: dict[str, Any] = {"grader_pattern": grader_pattern}
    if intent == "clarifying_question":
        patch["failure_pattern"] = NEEDS_MORE_INFO
        patch["assistant_intent"] = intent
    else:
        patch["failure_pattern"] = grader_pattern[0] if grader_pattern else UNKNOWN
        if intent != "answer":
            patch["assistant_intent"] = intent

    return patch, usage


async def classify_context_sufficiency(
    *,
    question: str | None,
    context: str | None,
    expected: str | None,
    llm: AnalysisLlmService,
) -> tuple[str | None, list[str], LlmUsageInfo | None]:
    """Judge whether retrieved context was sufficient to answer the question.

    Deliberately ignores the generated answer — this is the signal that separates
    a retrieval failure from a generation failure. Returns
    ``(verdict, missing_facts, usage)``; ``verdict`` is None on error.
    """
    ctx = (context or "").strip()
    if not ctx:
        return None, [], None

    parts = [f"Question:\n{(question or '').strip()[:_CONTEXT_MAX_CHARS]}"]
    if expected and expected.strip():
        parts.append(f"Expected answer:\n{expected.strip()[:_CONTEXT_MAX_CHARS]}")
    parts.append(f"Retrieved context:\n{ctx[:_CONTEXT_MAX_CHARS]}")

    try:
        content, usage = await llm.tracked_chat_completion(
            messages=[
                {"role": "system", "content": _SUFFICIENCY_SYSTEM},
                {"role": "user", "content": "\n\n".join(parts)},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning("Context-sufficiency judge call failed: %s", exc)
        return None, [], None

    try:
        parsed = json.loads(content)
        verdict = parsed.get("sufficiency")
        if verdict in _SUFFICIENCY_VALUES:
            missing = parsed.get("missing_facts") or []
            if not isinstance(missing, list):
                missing = []
            missing = [str(m) for m in missing][:10]
            return verdict, missing, usage
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return None, [], usage


async def compute_root_cause(
    *,
    pass_: bool,
    grader_pattern: list[str],
    affects_pass_map: dict[str, bool],
    question: str | None,
    output: str | None,
    expected: str | None,
    retrieval_context: str | None,
    llm: AnalysisLlmService | None,
) -> tuple[dict[str, Any], LlmUsageInfo | None]:
    """Attribute a failed eval to the retrieval or generation stage.

    Returns ``(patch, usage)``. ``patch`` is empty for passed tests; for failed
    tests it contains ``root_cause = {category, confidence, source, evidence,
    missing_facts}``. Deterministic-first: only calls the LLM when the existing
    graders can't disambiguate. ``usage`` is None unless the judge was called.
    """
    if pass_:
        return {}, None

    has_retrieval = bool((retrieval_context or "").strip())

    def _patch(category: RootCause, *, confidence: str, source: str,
               evidence: str, missing: list[str] | None = None) -> dict[str, Any]:
        rc: dict[str, Any] = {
            "category": category,
            "confidence": confidence,
            "source": source,
            "evidence": evidence,
        }
        if missing:
            rc["missing_facts"] = missing
        return {"root_cause": rc}

    # Stage 0 — gate: no retrieval observable, so we can't blame retrieval.
    if not has_retrieval:
        return _patch(
            "indeterminate", confidence="high", source="deterministic",
            evidence="No retrieval context captured — instrument retriever spans "
            "to enable retrieval-vs-generation attribution.",
        ), None

    failed = {_norm(g) for g in grader_pattern}
    configured = {_norm(n) for n in affects_pass_map}
    retrieval_failed = bool(failed & _RETRIEVAL_GRADERS)
    generation_failed = bool(failed & _GENERATION_GRADERS)
    has_retrieval_grader = bool(configured & _RETRIEVAL_GRADERS)

    # Stage 1 — deterministic from graders.
    if retrieval_failed:
        return _patch(
            "retrieval", confidence="high", source="deterministic",
            evidence="A retrieval grader (e.g. sourceRetrieval) failed — the "
            "expected source was not retrieved.",
        ), None
    if generation_failed and has_retrieval_grader:
        # Retrieval grader was configured and did not fail, yet a grounding grader did.
        return _patch(
            "generation", confidence="high", source="deterministic",
            evidence="Grounding grader (faithfulness/factualCorrectness) failed "
            "while the retrieval grader passed — the answer mishandled retrieved context.",
        ), None

    # Stage 2 — ambiguous: judge context sufficiency with one LLM call.
    if llm is None:
        return _patch(
            "indeterminate", confidence="low", source="deterministic",
            evidence="Could not attribute from graders and no LLM available for "
            "context-sufficiency judging.",
        ), None

    verdict, missing, usage = await classify_context_sufficiency(
        question=question, context=retrieval_context, expected=expected, llm=llm,
    )
    if verdict in ("insufficient", "partial"):
        return _patch(
            "retrieval", confidence="high" if verdict == "insufficient" else "low",
            source="llm",
            evidence=f"Retrieved context judged {verdict} to answer the question.",
            missing=missing,
        ), usage
    if verdict == "sufficient":
        category: RootCause = "generation" if generation_failed else "task_spec"
        evidence = (
            "Context was sufficient but the answer was unfaithful/incorrect."
            if generation_failed else
            "Context was sufficient and the answer looks grounded — likely an "
            "ambiguous question, ground-truth mismatch, or grader calibration issue."
        )
        return _patch(category, confidence="low", source="llm", evidence=evidence), usage

    # Judge unavailable/unparseable — fall back without a confident verdict.
    return _patch(
        "indeterminate", confidence="low", source="llm",
        evidence="Context-sufficiency judge did not return a usable verdict.",
    ), usage


def aggregate_root_causes(categories: Iterable[str | None]) -> dict[str, int]:
    """Count ``root_cause.category`` occurrences across results, ignoring ``None``."""
    out: dict[str, int] = {}
    for c in categories:
        if not c:
            continue
        out[c] = out.get(c, 0) + 1
    return out


def aggregate_run_patterns(patterns: Iterable[str | None]) -> dict[str, int]:
    """Count ``failure_pattern`` occurrences across results, ignoring ``None``."""
    out: dict[str, int] = {}
    for p in patterns:
        if not p:
            continue
        out[p] = out.get(p, 0) + 1
    return out
