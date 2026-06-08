"""LLM-based behavioral signal classification for a single trace.

Given a trace's input/output (and any error), an LLM labels which behavioral
signals apply — refusal, user frustration, task-incomplete, loop — each with a
confidence. The parsing is split into a pure ``parse_classification`` function so
it can be unit-tested without a live model.

These signals are written to ``trace_signals`` and later picked up by
``engine/signals.py``; they do not call out to the issue engine directly.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.models.base import BEHAVIORAL_SIGNAL_TYPES, SignalType
from app.services.analysis_llm import AnalysisLlmService, LlmUsageInfo

logger = logging.getLogger(__name__)

_VALID_VALUES = {s.value for s in BEHAVIORAL_SIGNAL_TYPES}

SYSTEM_PROMPT = (
    "You are a production-LLM behavior analyst. Given one trace (the user's input "
    "and the assistant's output), decide which of these behavioral signals apply:\n"
    "- refusal: the assistant declined or said it could not do the request.\n"
    "- user_frustration: the user is annoyed, repeating themselves, or complaining.\n"
    "- task_incomplete: the assistant stopped without actually completing the request.\n"
    "- loop: the assistant repeated the same step/answer or appears stuck.\n\n"
    "Only report a signal when you are reasonably confident it is present. Most "
    "healthy traces have NO signals — returning an empty list is correct and common.\n"
    'Respond with JSON only: {"signals": [{"type": "<one of the four>", '
    '"confidence": <0..1>, "detail": "<short reason>"}]}'
)


@dataclass
class BehavioralSignal:
    signal_type: SignalType
    confidence: float
    detail: str | None


def _truncate(value: Any, limit: int = 2000) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_trace_repr(*, name: str | None, trace_input: Any, trace_output: Any, error: str | None) -> str:
    """Compact text representation of a trace for the classifier prompt."""
    parts = [f"Trace name: {name or 'unknown'}"]
    parts.append(f"Input:\n{_truncate(json.dumps(trace_input, default=str))}")
    parts.append(f"Output:\n{_truncate(json.dumps(trace_output, default=str))}")
    if error:
        parts.append(f"Error: {_truncate(error, 400)}")
    return "\n\n".join(parts)


def parse_classification(content: str) -> list[BehavioralSignal]:
    """Parse the model's JSON response into validated behavioral signals.

    Tolerant: unknown types, out-of-range confidences, and malformed entries are
    dropped rather than raising. Garbage input yields an empty list.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []

    raw = data.get("signals")
    if not isinstance(raw, list):
        return []

    out: list[BehavioralSignal] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        type_value = item.get("type")
        if type_value not in _VALID_VALUES or type_value in seen:
            continue
        seen.add(type_value)

        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        detail = item.get("detail")
        out.append(
            BehavioralSignal(
                signal_type=SignalType(type_value),
                confidence=confidence,
                detail=_truncate(detail, 400) if detail else None,
            )
        )
    return out


async def classify_trace(
    trace_repr: str, llm: AnalysisLlmService
) -> tuple[list[BehavioralSignal], LlmUsageInfo]:
    """Classify one trace; returns (signals, usage)."""
    content, usage = await llm.tracked_chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": trace_repr},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return parse_classification(content), usage
