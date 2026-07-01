"""Aggregate a window of traces into multi-hop retrieval stats.

"Multi-hop" has several honest definitions in an agentic-RAG app, so this reports
each rather than collapsing them:

- **complexity** — the agent's own ``queryComplexity`` label (moderate/complex
  trigger the summary tier + a drill-down hop; simple stays single-pass);
- **drill_down** — the summary tier returned pages that were drilled into for
  chunks, a genuine sequential second retrieval;
- **expansion** — the question fanned out into more than one (parallel) sub-query;
- **search_calls** — more than one search call was issued.

Everything is derived on read from already-synced signals — ``queryComplexity`` /
``expandedQueryCount`` on trace metadata and the search span's funnel output
(``searchCallCount`` / ``summaryPages``) — so there is no schema change or re-sync.
Each definition's rate is over the requests where its signal was *observable*, so
a rate isn't diluted by traces that never carried it.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from app.schemas.analytics import (
    ComplexityBucket,
    HistogramBin,
    MultiHopDefinition,
    MultiHopResponse,
)

_COMPLEX_LEVELS = {"moderate", "complex"}
_COMPLEXITY_ORDER = ("simple", "moderate", "complex", "unclassified")
# Tail caps for the per-request distributions — everything at/above folds into a "N+" bin.
_QUERIES_CAP = 5
_CALLS_CAP = 6


def _histogram(counter: Counter[int], cap: int) -> list[HistogramBin]:
    """Sorted bins from a counter whose keys are already capped at ``cap``."""
    return [
        HistogramBin(value=v, count=counter[v], label=(f"{cap}+" if v >= cap else str(v)))
        for v in sorted(counter)
    ]


def _rate(multi: int, total: int) -> float | None:
    return round(multi / total, 4) if total else None


def build_multi_hop_response(
    trace_rows: Iterable[tuple[Any, dict | None]],
    search_by_trace: dict[str, tuple[dict, dict]],
) -> MultiHopResponse:
    """Aggregate ``(trace_id, metadata)`` rows + per-trace search span input/output.

    ``search_by_trace`` maps ``str(trace_id)`` → ``(span_input, span_output)`` for the
    project's search span; traces without one contribute only their metadata signals.
    """
    complexity_counter: Counter[str] = Counter()
    queries_hist: Counter[int] = Counter()
    calls_hist: Counter[int] = Counter()

    comp_total = comp_multi = 0
    exp_total = exp_multi = 0
    drill_total = drill_multi = 0
    calls_total = calls_multi = 0
    queries_sum = calls_sum = 0
    analyzed = 0
    requests_total = 0

    for tid, meta in trace_rows:
        requests_total += 1
        meta = meta or {}
        span_input, span_output = search_by_trace.get(str(tid), ({}, {}))
        observed = False

        # 1. Query complexity — the agent's own simple/moderate/complex label.
        raw_complexity = meta.get("queryComplexity")
        complexity = raw_complexity.lower() if isinstance(raw_complexity, str) else None
        if complexity in ("simple", "moderate", "complex"):
            complexity_counter[complexity] += 1
            comp_total += 1
            if complexity in _COMPLEX_LEVELS:
                comp_multi += 1
            observed = True
        else:
            complexity_counter["unclassified"] += 1

        # 3. Query expansion — expanded query count (metadata first, then the search input).
        expanded = meta.get("expandedQueryCount")
        if not isinstance(expanded, int):
            queries = span_input.get("queries")
            expanded = len(queries) if isinstance(queries, list) else None
        if isinstance(expanded, int) and expanded >= 1:
            exp_total += 1
            queries_sum += expanded
            queries_hist[min(expanded, _QUERIES_CAP)] += 1
            if expanded > 1:
                exp_multi += 1
            observed = True

        # 4. Multiple search calls — total search API calls the funnel logged.
        search_ran = False
        calls = span_output.get("searchCallCount")
        if isinstance(calls, int) and calls >= 1:
            search_ran = True
            calls_total += 1
            calls_sum += calls
            calls_hist[min(calls, _CALLS_CAP)] += 1
            if calls > 1:
                calls_multi += 1
            observed = True

        # 2. Drill-down hop — the summary tier returned pages to drill into (a genuine
        #    second sequential retrieval). Denominator is requests where search ran, so
        #    single-pass "simple" requests correctly count as no drill-down.
        if search_ran:
            drill_total += 1
            summary_pages = span_output.get("summaryPages")
            if isinstance(summary_pages, int) and summary_pages > 0:
                drill_multi += 1

        if observed:
            analyzed += 1

    definitions = [
        MultiHopDefinition(
            key="complexity",
            label="Complex query",
            description="Classified moderate or complex — triggers the summary tier and a "
            "drill-down second hop (simple queries stay single-pass).",
            multi_hop=comp_multi,
            total=comp_total,
            rate=_rate(comp_multi, comp_total),
        ),
        MultiHopDefinition(
            key="drill_down",
            label="Drill-down hop",
            description="Retrieved page summaries, then drilled into the top pages for chunks "
            "— a sequential second retrieval hop.",
            multi_hop=drill_multi,
            total=drill_total,
            rate=_rate(drill_multi, drill_total),
        ),
        MultiHopDefinition(
            key="expansion",
            label="Query expansion",
            description="Fanned out into more than one search query (parallel sub-queries).",
            multi_hop=exp_multi,
            total=exp_total,
            rate=_rate(exp_multi, exp_total),
        ),
        MultiHopDefinition(
            key="search_calls",
            label="Multiple search calls",
            description="Issued more than one search call across tiers and drill-down.",
            multi_hop=calls_multi,
            total=calls_total,
            rate=_rate(calls_multi, calls_total),
        ),
    ]

    complexity_buckets = [
        ComplexityBucket(level=level, count=complexity_counter[level])
        for level in _COMPLEXITY_ORDER
        if complexity_counter[level]
    ]

    return MultiHopResponse(
        requests_total=requests_total,
        requests_analyzed=analyzed,
        definitions=definitions,
        complexity=complexity_buckets,
        queries_per_request=_histogram(queries_hist, _QUERIES_CAP),
        search_calls_per_request=_histogram(calls_hist, _CALLS_CAP),
        avg_queries_per_request=round(queries_sum / exp_total, 2) if exp_total else None,
        avg_search_calls_per_request=round(calls_sum / calls_total, 2) if calls_total else None,
    )
