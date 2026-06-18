"""Derive a structured agentic-RAG pipeline view from a trace's spans.

LoopLM already persists each Langfuse observation's ``input``/``output`` verbatim, so the
full RAG funnel — queries → search → found sources → assembled context → answer → judge —
is reconstructable on read without any schema change or re-sync. This module locates the
relevant spans by their configured names (see ``retrieval_config.get_rag_span_names``) and
assembles a :class:`RagPipelineView`.

The one signal not present in current traces is the *score-drop funnel* (how many
candidates were filtered out); the schema carries those fields so they populate
automatically once rde-gpt logs them on the search span.
"""

from __future__ import annotations

import re
from typing import Any

from app.models.models import Trace
from app.schemas.traces import (
    RagCounts,
    RagJudge,
    RagJudgeCorrection,
    RagPipelineView,
    RagSearchFunnel,
    RagSource,
)
from app.services.retrieval_config import extract_rag_pipeline_sources, normalize_source_url

# ``[1] = https://…`` lines in the SOURCE_ORDER block the agent passes to the judge.
_SOURCE_ORDER_RE = re.compile(r"\[(\d+)\]\s*=\s*(https?://\S+)")
# ``[1]`` citation markers in the final answer.
_CITATION_RE = re.compile(r"\[(\d+)\]")


def _find_span(spans: list[Any], name: str | None):
    """First span whose name matches ``name`` (case-insensitive)."""
    if not name:
        return None
    target = name.strip().lower()
    for span in spans:
        if (span.name or "").strip().lower() == target:
            return span
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    """Coerce a span input/output into searchable text (str passthrough, else repr)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _extract_queries(search_span, query_span) -> list[str]:
    """Expanded queries, preferring the search span's input, then query-expansion."""
    for span in (search_span, query_span):
        if span is None:
            continue
        queries = _as_dict(span.input).get("queries") or _as_dict(span.output).get("queries")
        if isinstance(queries, list):
            out = [q for q in queries if isinstance(q, str) and q.strip()]
            if out:
                return out
    return []


def _extract_funnel(search_span) -> RagSearchFunnel | None:
    if search_span is None:
        return None
    out = _as_dict(search_span.output)
    if not out:
        return None
    return RagSearchFunnel(
        search_call_count=out.get("searchCallCount"),
        summary_pages=out.get("summaryPages"),
        chunk_results=out.get("chunkResults"),
        broadened=out.get("broadened"),
        has_results=out.get("hasResults"),
        candidates_before_filter=out.get("candidatesBeforeFilter"),
        dropped_by_relative_filter=out.get("droppedByRelativeFilter"),
        dropped_by_absolute_floor=out.get("droppedByAbsoluteFloor"),
        kept=out.get("kept"),
    )


def _parse_source_order(judge_span) -> dict[str, int]:
    """Map normalized source URL → citation index from the judge's SOURCE_ORDER block."""
    if judge_span is None:
        return {}
    text = _text(_as_dict(judge_span.input).get("prompt")) or _text(judge_span.input)
    order: dict[str, int] = {}
    for match in _SOURCE_ORDER_RE.finditer(text):
        idx = int(match.group(1))
        url = normalize_source_url(match.group(2).rstrip(".,;:!?"))
        order.setdefault(url, idx)
    return order


def _extract_answer(generation_span) -> str | None:
    if generation_span is None:
        return None
    out = generation_span.output
    if isinstance(out, str):
        return out
    if isinstance(out, dict):
        for key in ("output", "answer", "text", "content"):
            val = out.get(key)
            if isinstance(val, str):
                return val
    return None


def _extract_assembled_context(generation_span) -> str | None:
    """Pull the retrieved-context block injected into the final user message.

    rde-gpt embeds it after the ``SUCHERGEBNISSE AUS DER WISSENSDATENBANK:`` marker in the
    last user message rather than logging it as its own field.
    """
    if generation_span is None:
        return None
    messages = _as_dict(generation_span.input).get("messages")
    if not isinstance(messages, list):
        return None
    marker = "SUCHERGEBNISSE AUS DER WISSENSDATENBANK"
    for msg in reversed(messages):
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, str) and marker in content:
            return content[content.index(marker) :].strip()[:20000]
    return None


def _extract_judge(judge_span) -> RagJudge | None:
    if judge_span is None:
        return None
    out = _as_dict(judge_span.output)
    if not out:
        return None
    corrections = []
    for corr in out.get("corrections") or []:
        if isinstance(corr, dict):
            corrections.append(
                RagJudgeCorrection(
                    type=corr.get("type"),
                    find=corr.get("find"),
                    replacement=corr.get("replacement"),
                    reason=corr.get("reason"),
                )
            )
    passed = out.get("passed")
    return RagJudge(passed=passed if isinstance(passed, bool) else None, corrections=corrections)


def rag_pipeline_summary(view: RagPipelineView) -> dict[str, Any] | None:
    """Compact, persistable snapshot of a pipeline view for test-case provenance.

    Stored under a test case's ``metadata.rag_pipeline`` so the funnel that produced the
    case is visible later without re-deriving it. Returns None for non-RAG traces.
    """
    if not view.available:
        return None
    return {
        "found": view.counts.found,
        "used_in_context": view.counts.used_in_context,
        "cited": view.counts.cited,
        "used_source_urls": [s.url for s in view.sources if s.selected and s.url],
        "judge_passed": view.judge.passed if view.judge else None,
        "queries": view.queries,
    }


def build_rag_pipeline(trace: Trace, span_names: dict[str, str]) -> RagPipelineView:
    """Assemble the RAG pipeline view for ``trace`` using the configured span names.

    Returns a view with ``available=False`` when none of the RAG spans are present, so
    callers can fall back to the generic span tree for non-RAG traces.
    """
    spans = list(trace.spans or [])
    if not spans:
        return RagPipelineView(available=False)

    query_span = _find_span(spans, span_names.get("query_expansion"))
    search_span = _find_span(spans, span_names.get("search"))
    retrieval_span = _find_span(spans, span_names.get("retrieval_context"))
    generation_span = _find_span(spans, span_names.get("generation"))
    judge_span = _find_span(spans, span_names.get("judge"))

    if not any((search_span, retrieval_span, generation_span)):
        return RagPipelineView(available=False)

    queries = _extract_queries(search_span, query_span)
    funnel = _extract_funnel(search_span)
    answer = _extract_answer(generation_span)
    assembled_context = _extract_assembled_context(generation_span)
    judge = _extract_judge(judge_span)

    raw_sources = extract_rag_pipeline_sources(retrieval_span.output) if retrieval_span else []
    source_order = _parse_source_order(judge_span)
    cited_indices = {int(m) for m in _CITATION_RE.findall(answer or "")}

    # Prefer explicit per-source selection (rde-gpt Phase 2); otherwise infer which
    # sources reached the context by matching their URL against the judge's source order.
    has_explicit = any(s.get("selected") is not None for s in raw_sources)
    sources: list[RagSource] = []
    used = 0
    for s in raw_sources:
        url = s.get("url")
        if has_explicit:
            selected = bool(s.get("selected"))
            citation_index = s.get("citation_index")
            exact = True
        else:
            citation_index = source_order.get(url) if url else None
            selected = citation_index is not None
            exact = False
        if selected:
            used += 1
        sources.append(
            RagSource(
                title=s.get("title"),
                url=url,
                score=s.get("score"),
                score_scale=s.get("score_scale"),
                tool_name=s.get("tool_name"),
                content_preview=(s.get("content_preview") or None) and str(s["content_preview"])[:500],
                selected=selected,
                citation_index=citation_index if isinstance(citation_index, int) else None,
                selection_exact=exact,
            )
        )

    cited = len({s.citation_index for s in sources if s.selected and s.citation_index in cited_indices})
    if not cited and cited_indices:
        cited = len(cited_indices)

    counts = RagCounts(found=len(sources), used_in_context=used, cited=cited)
    query_complexity = (trace.trace_metadata or {}).get("queryComplexity")

    return RagPipelineView(
        available=True,
        queries=queries,
        query_complexity=query_complexity if isinstance(query_complexity, str) else None,
        search=funnel,
        sources=sources,
        assembled_context=assembled_context,
        answer=answer,
        answer_tokens_in=generation_span.tokens_in if generation_span else None,
        answer_tokens_out=generation_span.tokens_out if generation_span else None,
        answer_model=generation_span.model if generation_span else None,
        judge=judge,
        counts=counts,
    )
