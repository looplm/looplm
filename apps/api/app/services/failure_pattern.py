"""Failure-pattern classification for eval results.

Two layers:
- ``derive_grader_pattern``: deterministic — which ``affects_pass`` graders failed.
- ``classify_assistant_intent``: one short LLM call — flags clarifying questions.
- ``compute_failure_pattern``: combines both into a stable ``failure_pattern`` label.

Storage shape (lives on ``EvalResult.result_metadata`` JSONB):
- ``failure_pattern``: short label, e.g. ``"faithfulness"`` or ``"needs_more_info"``.
- ``grader_pattern``: sorted list of affects-pass graders that failed.
- ``assistant_intent`` (optional): one of {clarifying_question, refusal, other}.
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

_CLASSIFIER_SYSTEM = (
    "You classify an assistant's reply in an LLM evaluation. "
    'Return ONLY a JSON object of the form {"intent": "<value>"}, no prose. '
    "Allowed values:\n"
    '- "answer": the assistant attempted to answer the user.\n'
    '- "clarifying_question": the assistant asked the user a follow-up '
    "question because it needed more information.\n"
    '- "refusal": the assistant refused or said it could not answer.\n'
    '- "other": none of the above.'
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


def aggregate_run_patterns(patterns: Iterable[str | None]) -> dict[str, int]:
    """Count ``failure_pattern`` occurrences across results, ignoring ``None``."""
    out: dict[str, int] = {}
    for p in patterns:
        if not p:
            continue
        out[p] = out.get(p, 0) + 1
    return out
