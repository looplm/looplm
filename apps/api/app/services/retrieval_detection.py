"""LLM-assisted detection of a project's retrieval-context source.

Samples recent traces, gathers the candidate sources (top-level response-payload
keys and span name/type pairs), and asks the analysis LLM to pick the one that
holds the retrieved RAG context. The pick is returned for confirmation — it is
*not* persisted here; the caller saves it to ``project.settings`` via the normal
settings update.

See ``retrieval_config`` for how the stored ``retrieval_source`` is consumed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integrations import Integration, Span, Trace
from app.models.project import Project
from app.services.analysis_llm import AnalysisLlmService
from app.services.retrieval_config import VALID_KINDS

logger = logging.getLogger(__name__)

_TRACE_SAMPLE = 25
_SPAN_SAMPLE = 200
_VALUE_PREVIEW_CHARS = 300
_MAX_PAYLOAD_KEYS = 40
_MAX_SPANS = 40

_SYSTEM = (
    "You are configuring an LLM-observability tool. Given candidate data sources "
    "sampled from a project's traces, identify which one carries the RETRIEVED "
    "CONTEXT of a RAG pipeline — the list of document chunks / passages / sources "
    "fetched to ground the answer. It is NOT the final answer, the user question, "
    "token usage, or unrelated metadata.\n\n"
    "Choose exactly one of two source kinds:\n"
    "- payload_key: a top-level key in the response payload whose value holds the "
    "retrieved context (e.g. retrievedContext, formattedContext, searchSources).\n"
    "- span: a span identified by name whose output holds the retrieved context.\n\n"
    "When BOTH a payload key and a span plausibly hold the retrieved context, "
    "prefer payload_key — it also applies to live eval-run responses, which have "
    "no spans.\n\n"
    'Reply with JSON: {"kind": "payload_key"|"span"|"none", "value": "<key or '
    'span name>", "confidence": "high"|"medium"|"low", "reasoning": "<one '
    'sentence>"}. Use "none" only when no candidate plausibly holds retrieved '
    "context."
)


def _preview(value: Any) -> str:
    """Short, type-tagged preview of a candidate value for the prompt."""
    if isinstance(value, str):
        return f"str: {value[:_VALUE_PREVIEW_CHARS]}"
    if isinstance(value, list):
        head = json.dumps(value[:2], ensure_ascii=False, default=str)
        return f"list[{len(value)}]: {head[:_VALUE_PREVIEW_CHARS]}"
    if isinstance(value, dict):
        return f"dict keys={list(value.keys())[:12]}"
    return f"{type(value).__name__}: {str(value)[:120]}"


async def _gather_candidates(
    db: AsyncSession, project: Project
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Collect payload-key and span candidates from recent traces.

    Returns ``(payload_keys, spans)`` where each entry has a name and a sample
    preview. First occurrence of each key/span name wins (newest traces first).
    """
    integration_ids = select(Integration.id).where(Integration.project_id == project.id)

    trace_rows = (
        await db.execute(
            select(Trace.id, Trace.output)
            .where(Trace.integration_id.in_(integration_ids))
            .order_by(desc(Trace.start_time))
            .limit(_TRACE_SAMPLE)
        )
    ).all()

    payload_keys: dict[str, str] = {}
    trace_ids: list[Any] = []
    for trace_id, output in trace_rows:
        trace_ids.append(trace_id)
        if isinstance(output, dict):
            for key, value in output.items():
                if key not in payload_keys:
                    payload_keys[key] = _preview(value)

    spans: dict[str, str] = {}
    if trace_ids:
        span_rows = (
            await db.execute(
                select(Span.name, Span.type, Span.output)
                .where(Span.trace_id.in_(trace_ids))
                .order_by(desc(Span.created_at))
                .limit(_SPAN_SAMPLE)
            )
        ).all()
        for name, type_, output in span_rows:
            if not name:
                continue
            type_label = type_.value if type_ is not None else "unknown"
            label = f"{name} ({type_label})"
            if label not in spans:
                spans[label] = _preview(output)

    payload_list = [
        {"key": k, "sample": v} for k, v in list(payload_keys.items())[:_MAX_PAYLOAD_KEYS]
    ]
    span_list = [
        {"name": k, "sample": v} for k, v in list(spans.items())[:_MAX_SPANS]
    ]
    return payload_list, span_list


def _build_prompt(payload_keys: list[dict[str, str]], spans: list[dict[str, str]]) -> str:
    lines = ["Top-level response-payload keys:"]
    if payload_keys:
        lines += [f"  - {c['key']} — {c['sample']}" for c in payload_keys]
    else:
        lines.append("  (none observed)")
    lines.append("")
    lines.append("Spans (name + type):")
    if spans:
        lines += [f"  - {c['name']} — {c['sample']}" for c in spans]
    else:
        lines.append("  (none observed)")
    return "\n".join(lines)


def _parse_suggestion(
    content: str, payload_keys: list[dict[str, str]], spans: list[dict[str, str]]
) -> dict[str, Any] | None:
    """Parse and validate the LLM JSON pick against the observed candidates."""
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    kind = parsed.get("kind")
    value = parsed.get("value")
    if kind == "none" or kind not in VALID_KINDS or not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()

    # Guard against hallucinated values — must match a sampled candidate. Span
    # candidates carry a " (type)" suffix in the prompt, so match on the name part.
    if kind == "payload_key":
        valid = {c["key"] for c in payload_keys}
    else:
        valid = {c["name"].rsplit(" (", 1)[0] for c in spans}
    if value not in valid:
        logger.info("Retrieval detection: LLM returned non-candidate value %r", value)
        return None

    confidence = parsed.get("confidence")
    if confidence not in ("high", "medium", "low"):
        confidence = "low"
    reasoning = parsed.get("reasoning")
    return {
        "kind": kind,
        "value": value,
        "confidence": confidence,
        "reasoning": str(reasoning)[:500] if reasoning else None,
    }


async def detect_retrieval_source(
    db: AsyncSession, project: Project, llm: AnalysisLlmService
) -> dict[str, Any]:
    """Detect the project's retrieval-context source from sampled traces.

    Returns ``{"suggestion": {...}|None, "candidates": {...}, "usage": LlmUsageInfo|None}``.
    Does not persist — the caller saves the chosen source to ``project.settings``.
    """
    payload_keys, spans = await _gather_candidates(db, project)
    candidates = {"payload_keys": payload_keys, "spans": spans}

    if not payload_keys and not spans:
        return {"suggestion": None, "candidates": candidates, "usage": None}

    content, usage = await llm.tracked_chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _build_prompt(payload_keys, spans)},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    suggestion = _parse_suggestion(content, payload_keys, spans)
    return {"suggestion": suggestion, "candidates": candidates, "usage": usage}
