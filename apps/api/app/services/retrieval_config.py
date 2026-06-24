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
import re
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


# Confluence Cloud URLs in retrieval payloads carry a trailing slug after
# ``/pages/<id>/`` that often contains malformed or double-encoded characters.
# Confluence resolves the bare ``/pages/<id>`` form to the same page, so trim
# the slug to keep the link clickable.
_CONFLUENCE_PAGE_URL = re.compile(
    r"^(https?://[^/]+/wiki/spaces/[^/]+/pages/\d+)(?:/.*)?$",
    re.IGNORECASE,
)


def normalize_source_url(url: str) -> str:
    match = _CONFLUENCE_PAGE_URL.match(url)
    if match:
        return match.group(1)
    return url


def extract_retrieval_source_urls(span_output: Any) -> list[str]:
    """Pull source URLs out of a retrieval-context span's output payload.

    Accepts ``{"sources": [{"url": "...", ...}, ...]}`` as well as a bare
    list of source dicts — payload keys like ``searchSources`` hold the list
    directly rather than wrapping it. Each source's ``url`` is read, falling
    back to ``pageUrl``. Returns a de-duplicated list preserving original
    order. Non-string and blank URLs are skipped so we never persist garbage
    as expected sources.
    """
    if isinstance(span_output, dict):
        sources = span_output.get("sources")
    else:
        sources = span_output
    if not isinstance(sources, list):
        return []
    seen: set[str] = set()
    urls: list[str] = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        url = src.get("url") or src.get("pageUrl")
        if not isinstance(url, str):
            continue
        url = normalize_source_url(url.strip())
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def extract_rag_pipeline_sources(span_output: Any) -> list[dict[str, Any]]:
    """Pull structured sources out of a retrieval-context span's output.

    Sibling to :func:`extract_retrieval_source_urls` that keeps the full per-source
    struct (title, score, tool, content preview) instead of collapsing to URLs — used
    by the RAG-pipeline view. Accepts ``{"sources": [...]}`` or a bare list. The URL is
    normalized; everything else is passed through. Order is preserved and *not*
    de-duplicated (the found set legitimately contains the same page from multiple
    tools, which the funnel surfaces).
    """
    if isinstance(span_output, dict):
        sources = span_output.get("sources")
    else:
        sources = span_output
    if not isinstance(sources, list):
        return []
    out: list[dict[str, Any]] = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        raw_url = src.get("url") or src.get("pageUrl")
        url = normalize_source_url(raw_url.strip()) if isinstance(raw_url, str) and raw_url.strip() else None

        def _num(value: Any) -> float | None:
            return value if isinstance(value, (int, float)) else None

        # Stable chunk identity (Azure AI Search document key). rde-gpt logs it as
        # ``chunkId`` on chunk sources; the eval payload's ``searchSources`` carry it as
        # ``id``. Used to attach human relevance labels at the chunk level.
        chunk_id = src.get("chunkId") or src.get("chunk_id") or src.get("id") or src.get("key")
        meta = src.get("metadata") if isinstance(src.get("metadata"), dict) else {}
        pdf_page = (
            src.get("pdfPageNumber")
            or src.get("pdf_page_number")
            or meta.get("pdf_page_number")
            or meta.get("pageNumber")
            or meta.get("page")
        )
        out.append(
            {
                "chunk_id": str(chunk_id) if chunk_id is not None else None,
                "title": src.get("title") or src.get("pageTitle"),
                "url": url,
                "score": _num(src.get("score")),
                "score_scale": src.get("scoreScale"),
                # Raw pre/post-rerank scores — present once rde-gpt logs them; enable the
                # before/after-rerank rank diff in the pipeline view.
                "original_score": _num(src.get("originalScore")),
                "reranker_score": _num(src.get("rerankerScore")),
                "tool_name": src.get("tool_name") or src.get("toolName"),
                # Full chunk text plus a short preview — the labeling UI shows the whole chunk.
                "content": src.get("content") or src.get("contentPreview"),
                "content_preview": src.get("contentPreview") or src.get("content"),
                # Chunk locators: where in the document this passage sits.
                "heading_context": src.get("headingContext") or src.get("heading_context"),
                "pdf_page_number": pdf_page if isinstance(pdf_page, int) else None,
                # Honored when present (rde-gpt logs these explicitly);
                # otherwise the pipeline service infers them from the source order.
                "selected": src.get("selected"),
                "citation_index": src.get("citationIndex"),
            }
        )
    return out


# Default span names for the agentic-RAG steps, matching the rde-gpt instrumentation.
# Per-project overrides live under ``Project.settings["rag_span_names"]``. The
# ``retrieval_context`` entry intentionally defers to ``get_retrieval_span_name`` so the
# existing per-project ``retrieval_source`` setting keeps working as the single source of
# truth for that one step.
RAG_SPAN_NAME_DEFAULTS: dict[str, str] = {
    "query_expansion": "query-expansion",
    "search": "mandatory-search",
    "retrieval_context": DEFAULT_RETRIEVAL_SPAN_NAME,
    "generation": "llm-generation",
    "judge": "response-judge-llm",
}


def get_rag_span_names(project: Project) -> dict[str, str]:
    """Span names for each agentic-RAG step, with per-project overrides applied.

    Returns a complete map keyed by step (``query_expansion``, ``search``,
    ``retrieval_context``, ``generation``, ``judge``). ``retrieval_context`` resolves via
    :func:`get_retrieval_span_name` so it honors the structured ``retrieval_source``
    setting; the rest read from ``Project.settings["rag_span_names"]`` falling back to
    :data:`RAG_SPAN_NAME_DEFAULTS`.
    """
    names = dict(RAG_SPAN_NAME_DEFAULTS)
    overrides = (project.settings or {}).get("rag_span_names")
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if key in names and isinstance(value, str) and value.strip():
                names[key] = value.strip()
    names["retrieval_context"] = get_retrieval_span_name(project)
    return names


_URL_RE = re.compile(r"""https?://[^\s"'<>\)\]\\]+""")


def extract_retrieved_urls(
    raw_response: str, *, payload_key: str | None = None, limit: int = 30
) -> list[str]:
    """Extract the URLs a RAG response actually retrieved, for grader details.

    Tries the structured ``{"sources": [{"url": ...}]}`` shape first (top level,
    then under the retrieval-context payload key), falling back to regexing URLs
    out of the retrieval context text, then the full raw response. Returns a
    de-duplicated, order-preserving list capped at ``limit``.
    """
    if not raw_response:
        return []
    try:
        parsed = json.loads(raw_response)
    except (json.JSONDecodeError, TypeError):
        parsed = None

    urls: list[str] = []
    if isinstance(parsed, dict):
        urls = extract_retrieval_source_urls(parsed)
        if not urls:
            keys: list[str] = []
            if payload_key:
                keys.append(payload_key)
            keys.extend(k for k in _FALLBACK_PAYLOAD_KEYS if k != payload_key)
            for key in keys:
                urls = extract_retrieval_source_urls(parsed.get(key))
                if urls:
                    break

    if not urls:
        # Regex the retrieval-context text first so answer-only URLs don't leak
        # in; when it holds no URLs (e.g. plain-text chunks), fall back to the
        # full raw response rather than reporting nothing was retrieved.
        texts = []
        if isinstance(parsed, dict):
            ctx = extract_retrieval_context_from_payload(parsed, payload_key=payload_key)
            if ctx:
                texts.append(ctx)
        texts.append(raw_response)
        for text in texts:
            seen: set[str] = set()
            for match in _URL_RE.finditer(text):
                url = normalize_source_url(match.group(0).rstrip(".,;:!?"))
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
            if urls:
                break

    return urls[:limit]


def extract_retrieved_chunks(
    parsed: Any, *, payload_key: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Structured, ranked retrieved chunks from a parsed response payload.

    For the chunk-level labeling path: locates the sources array under the common keys
    (``searchSources`` first, then the configured ``payload_key``, then the fallbacks,
    then a top-level ``sources``) and returns order-preserved dicts with
    ``chunk_id``/``title``/``url``/``score``/``content_preview``. Order is the retrieval
    rank, which the metrics rely on. Returns ``[]`` when ``parsed`` is not a dict or no
    sources array is found.
    """
    if not isinstance(parsed, dict):
        return []
    keys: list[str] = ["searchSources"]
    if payload_key:
        keys.append(payload_key)
    keys.extend(k for k in _FALLBACK_PAYLOAD_KEYS if k not in keys)
    keys.append("sources")

    sources: list[dict[str, Any]] = []
    for key in keys:
        sources = extract_rag_pipeline_sources(parsed.get(key))
        if sources:
            break

    out: list[dict[str, Any]] = []
    for s in sources[:limit]:
        preview = s.get("content_preview")
        content = s.get("content")
        out.append(
            {
                "chunk_id": s.get("chunk_id"),
                "title": s.get("title"),
                "url": s.get("url"),
                "score": s.get("score"),
                # Full chunk text (generously capped) so the labeler can read the whole
                # passage, plus a short preview for the collapsed row.
                "content": str(content)[:8000] if content else None,
                "content_preview": str(preview)[:600] if preview else None,
                "heading_context": s.get("heading_context"),
                "pdf_page_number": s.get("pdf_page_number"),
            }
        )
    return out
