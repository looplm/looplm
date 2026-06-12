"""Shared helper for the per-project retrieval source setting.

The retrieval/RAG step in a trace can be identified two ways, depending on how
the agent is instrumented:

- **span** — a span with a known *name* (e.g. ``retrieval-context``) carries the
  retrieved chunks in its output. This is what the span-based analytics, coverage
  and dataset builders query (by ``Span.name``), so it stays the source of truth
  for those.
- **payload_key** — the retrieved context is a top-level field in the response
  payload (e.g. ``retrievedContext``/``formattedContext``) rather than a dedicated
  span. Common for agents that retrieve via a tool call.

Both are stored under one structured ``retrieval_source`` setting so a single
auto-detector (see ``retrieval_detection``) can pick whichever fits a project.
The legacy ``retrieval_span_name`` string key is still honored for backwards
compatibility. This module is the single source of truth for the keys, the
default, and the extraction fallback.
"""

from __future__ import annotations

import json
from typing import Any

from app.models.project import Project

# Legacy flat key — a bare span name. Still read so existing projects keep working.
SETTINGS_KEY = "retrieval_span_name"
# New structured key — {"kind": "span"|"payload_key", "value": str, ...}.
SOURCE_SETTINGS_KEY = "retrieval_source"
DEFAULT_RETRIEVAL_SPAN_NAME = "retrieval-context"
VALID_KINDS = ("span", "payload_key")

# Top-level payload keys tried when no key is configured (or the configured key
# doesn't match) — keeps common RAG response shapes working without detection.
# Important for eval runs against a live endpoint: those responses have no spans,
# so a span-kind ``retrieval_source`` contributes nothing there and these
# fallbacks are the only way to capture retrieval context.
_FALLBACK_PAYLOAD_KEYS = (
    "retrieval_context",
    "retrievalContext",
    "retrievedContext",
    "formattedContext",
    "searchSources",
    "context",
)


def get_retrieval_source_from_settings(settings: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the structured retrieval-source config from a raw settings dict."""
    raw = (settings or {}).get(SOURCE_SETTINGS_KEY)
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    value = raw.get("value")
    if kind in VALID_KINDS and isinstance(value, str) and value.strip():
        return {
            "kind": kind,
            "value": value.strip(),
            "confidence": raw.get("confidence"),
            "reasoning": raw.get("reasoning"),
            "detected_at": raw.get("detected_at"),
        }
    return None


def get_retrieval_source(project: Project) -> dict[str, Any] | None:
    """Return the structured retrieval-source config, or None when unset/invalid."""
    return get_retrieval_source_from_settings(project.settings)


def get_retrieval_payload_key_from_settings(settings: dict[str, Any] | None) -> str | None:
    """Configured top-level retrieval payload key from a raw settings dict, if any."""
    src = get_retrieval_source_from_settings(settings)
    if src and src["kind"] == "payload_key":
        return src["value"]
    return None


def get_retrieval_span_name(project: Project) -> str:
    """Span name the project uses for its retrieval/RAG step.

    Reads the structured ``retrieval_source`` (when ``kind == "span"``) first,
    then the legacy flat key, then the default. Always returns a name so the
    span-based analytics/coverage queries keep working even when a project's
    retrieval is actually payload-key based (they simply won't match, which is
    the honest current state).
    """
    src = get_retrieval_source(project)
    if src and src["kind"] == "span":
        return src["value"]
    raw = (project.settings or {}).get(SETTINGS_KEY)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return DEFAULT_RETRIEVAL_SPAN_NAME


def get_retrieval_payload_key(project: Project) -> str | None:
    """Top-level response-payload key holding retrieval context, if configured."""
    return get_retrieval_payload_key_from_settings(project.settings)


def extract_retrieval_context_from_payload(
    parsed: Any, *, payload_key: str | None = None, max_chars: int = 10000
) -> str | None:
    """Pull retrieval context out of a parsed response payload.

    Tries the configured ``payload_key`` first (when given), then the default
    fallback keys. Returns a truncated string, or None when nothing matches or
    ``parsed`` is not a dict.
    """
    if not isinstance(parsed, dict):
        return None
    keys: list[str] = []
    if payload_key:
        keys.append(payload_key)
    keys.extend(k for k in _FALLBACK_PAYLOAD_KEYS if k != payload_key)
    for key in keys:
        ctx = parsed.get(key)
        if not ctx:
            continue
        if isinstance(ctx, str):
            return ctx[:max_chars]
        if isinstance(ctx, (dict, list)):
            return json.dumps(ctx, ensure_ascii=False, default=str)[:max_chars]
    return None
