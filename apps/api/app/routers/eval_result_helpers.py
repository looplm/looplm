"""Metadata helpers for shaping eval result payloads."""
from __future__ import annotations

import json
from typing import Any

from app.schemas.evaluations import GraderResultSummary
from app.services.retrieval_config import extract_retrieval_context_from_payload


def _extract_target_usage(parsed: dict[str, Any]) -> dict[str, int] | None:
    """Pull the target generation call's token usage from its response payload.

    Handles the OpenAI-shaped ``usage`` object in either camelCase (``promptTokens``)
    or snake_case (``prompt_tokens``). Returns None when the target reports no usage.
    """
    usage = parsed.get("usage")
    if not isinstance(usage, dict):
        return None
    pt = usage.get("promptTokens", usage.get("prompt_tokens"))
    ct = usage.get("completionTokens", usage.get("completion_tokens"))
    if not isinstance(pt, (int, float)) and not isinstance(ct, (int, float)):
        return None
    pt = int(pt or 0)
    ct = int(ct or 0)
    return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}


def _enrich_result_metadata(
    meta: dict[str, Any] | None, *, payload_key: str | None = None
) -> dict[str, Any]:
    """Enrich eval result metadata (read-time) for the row modal.

    Adds, when present in the target's raw response and not already stored:
    - ``retrieval_context``: the (truncated) retrieval context snippet.
    - ``target_usage``: the generation LLM's token usage (input/output/total).
    - ``model_context``: the full ``formattedContext`` block fed into the generation
      prompt — untruncated, unlike ``retrieval_context``. This is the context the
      model saw; the target does not return the literal system prompt.
    """
    meta = meta or {}
    raw = meta.get("raw_response")
    if not raw:
        return meta
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return meta
    if not isinstance(parsed, dict):
        return meta

    enriched = dict(meta)
    if "retrieval_context" not in enriched:
        ctx = extract_retrieval_context_from_payload(parsed, payload_key=payload_key)
        if ctx:
            enriched["retrieval_context"] = ctx

    usage = _extract_target_usage(parsed)
    if usage:
        enriched["target_usage"] = usage

    fc = parsed.get("formattedContext")
    if isinstance(fc, str) and fc.strip():
        enriched["model_context"] = fc

    return enriched


def _summarize_graders(graders: dict[str, Any] | None) -> dict[str, GraderResultSummary]:
    """Trim each grader to (pass, reason, skipped) for the list payload."""
    out: dict[str, GraderResultSummary] = {}
    for name, g in (graders or {}).items():
        if not isinstance(g, dict):
            continue
        out[name] = GraderResultSummary(
            **{"pass": bool(g.get("pass", False))},
            reason=g.get("reason"),
            skipped=bool(g.get("skipped", False)),
        )
    return out


def _turn_count(metadata: dict[str, Any] | None) -> int | None:
    history = (metadata or {}).get("conversation_history")
    if isinstance(history, list):
        return len(history)
    return None


def _grader_pattern(metadata: dict[str, Any] | None) -> list[str]:
    val = (metadata or {}).get("grader_pattern")
    if isinstance(val, list):
        return [str(x) for x in val]
    return []


def _failure_pattern(metadata: dict[str, Any] | None) -> str | None:
    val = (metadata or {}).get("failure_pattern")
    return str(val) if val else None


def _root_cause_category(metadata: dict[str, Any] | None) -> str | None:
    rc = (metadata or {}).get("root_cause")
    if isinstance(rc, dict):
        cat = rc.get("category")
        return str(cat) if cat else None
    return None
