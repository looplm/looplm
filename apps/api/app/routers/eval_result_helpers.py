"""Metadata helpers for shaping eval result payloads."""
from __future__ import annotations

import json
from typing import Any

from app.schemas.evaluations import GraderResultSummary
from app.services.retrieval_config import extract_retrieval_context_from_payload


def _enrich_result_metadata(
    meta: dict[str, Any] | None, *, payload_key: str | None = None
) -> dict[str, Any]:
    """Enrich eval result metadata with retrieval_context extracted from raw_response."""
    meta = meta or {}
    if "retrieval_context" in meta:
        return meta
    raw = meta.get("raw_response")
    if not raw:
        return meta
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return meta
    ctx = extract_retrieval_context_from_payload(parsed, payload_key=payload_key)
    if ctx:
        enriched = dict(meta)
        enriched["retrieval_context"] = ctx
        return enriched
    return meta


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
