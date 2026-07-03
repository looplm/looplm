"""Roll a window of traces up into the aggregate retrieval pipeline flow chart.

Reuses :func:`app.services.rag_pipeline.build_rag_pipeline` per trace — the same
on-read reconstruction that powers the single-trace RAG view — and aggregates the
resulting :class:`RagPipelineView` objects onto a fixed canonical topology. No schema
change or re-sync: everything is derived from already-synced span input/output.

The topology is fixed (it does not grow or shrink with the data) so each node can carry
honest stats *and* a ``status`` saying whether the stage was actually observable. Stages
whose signal rde-gpt does not log yet (score-drop funnel, rerank scores) surface as
``no_data`` rather than silently reading as zero.
"""

from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Iterable

from app.models.models import Trace
from app.schemas.retrieval import (
    RetrievalMetric,
    RetrievalPipelineEdge,
    RetrievalPipelineNode,
    RetrievalPipelineResponse,
)
from app.schemas.traces import RagPipelineView
from app.services.rag_pipeline import build_rag_pipeline

_AZURE = "Azure AI Search"


def _fmt_pct(x: float | None) -> str:
    return f"{round(x * 100)}%" if x is not None else "—"


def _fmt_num(x: float | None, digits: int = 1) -> str:
    return f"{x:.{digits}f}" if x is not None else "—"


def _safe_mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _rate(count: int, total: int) -> float | None:
    return count / total if total else None


def _zero_result_tone(rate: float | None) -> str:
    if rate is None:
        return "muted"
    if rate > 0.10:
        return "bad"
    if rate > 0.02:
        return "warn"
    return "good"


def _pass_tone(rate: float | None) -> str:
    if rate is None:
        return "muted"
    if rate >= 0.90:
        return "good"
    if rate >= 0.70:
        return "warn"
    return "bad"


def build_retrieval_pipeline_aggregate(
    traces: Iterable[Trace], span_names: dict[str, str]
) -> RetrievalPipelineResponse:
    """Build the aggregate pipeline view from ``traces`` using configured span names."""
    trace_list = list(traces)
    pipelines = [build_rag_pipeline(t, span_names) for t in trace_list]
    rag: list[RagPipelineView] = [p for p in pipelines if p.available]
    n = len(rag)

    if n == 0:
        return RetrievalPipelineResponse(
            available=False,
            traces_analyzed=len(trace_list),
            rag_traces=0,
            span_names=span_names,
        )

    nodes = [
        _query_node(rag),
        _query_expansion_node(rag),
        _embeddings_node(rag),
        _keyword_node(),
        _vector_node(),
        _rrf_node(rag),
        _rerank_node(rag),
        _filter_node(rag),
        _context_node(rag),
        _generation_node(rag),
        _judge_node(rag),
    ]

    def edge(src: str, dst: str, label: str | None = None, kind: str = "main") -> RetrievalPipelineEdge:
        return RetrievalPipelineEdge(source=src, target=dst, label=label, kind=kind)

    edges = [
        edge("query", "query_expansion"),
        edge("query_expansion", "embeddings"),
        edge("embeddings", "keyword"),
        edge("embeddings", "vector"),
        edge("keyword", "rrf"),
        edge("vector", "rrf"),
        edge("rrf", "rerank"),
        edge("rerank", "score_filter"),
        edge("score_filter", "context_assembly"),
        edge("context_assembly", "generation"),
        edge("generation", "judge"),
        # Broadening: when the filtered pass keeps nothing, rde-gpt re-runs the SAME expanded
        # queries with the team/tag/source filters dropped (all teams + sources) — a fresh
        # hybrid search call, not a re-expansion. So the loop returns to the hybrid search
        # (RRF) rather than to query expansion.
        edge("score_filter", "rrf", label="no hits → retry without filters", kind="fallback"),
    ]

    return RetrievalPipelineResponse(
        available=True,
        traces_analyzed=len(trace_list),
        rag_traces=n,
        nodes=nodes,
        edges=edges,
        span_names=span_names,
    )


# --- Per-node builders -------------------------------------------------------------


def _query_node(rag: list[RagPipelineView]) -> RetrievalPipelineNode:
    n = len(rag)
    return RetrievalPipelineNode(
        id="query",
        label="User Query",
        sublabel="incoming request",
        description="The user question that enters the retrieval pipeline.",
        metrics=[RetrievalMetric(label="RAG requests", value=str(n))],
    )


def _query_expansion_node(rag: list[RagPipelineView]) -> RetrievalPipelineNode:
    counts = [len(p.queries) for p in rag if p.queries]
    avg = _safe_mean([float(c) for c in counts])
    multi = sum(1 for c in counts if c > 1)
    expansion_rate = _rate(multi, len(counts)) if counts else None
    status = "active" if counts else "no_data"
    return RetrievalPipelineNode(
        id="query_expansion",
        label="Query Expansion",
        sublabel="1 → N sub-queries",
        description="Rewrites the question into multiple search queries to widen recall.",
        status=status,
        metrics=[
            RetrievalMetric(label="avg queries / request", value=_fmt_num(avg)),
            RetrievalMetric(
                label="expanded", value=_fmt_pct(expansion_rate),
                hint="share of requests that produced more than one query",
            ),
        ],
    )


def _embeddings_node(rag: list[RagPipelineView]) -> RetrievalPipelineNode:
    # Not a dedicated field on the pipeline view — one embedding is generated per
    # expanded query, so the query count is the honest proxy.
    counts = [len(p.queries) for p in rag if p.queries]
    avg = _safe_mean([float(c) for c in counts])
    return RetrievalPipelineNode(
        id="embeddings",
        label="Embeddings",
        sublabel="one per query",
        description="Each query is embedded for the vector arm of hybrid search.",
        status="active" if counts else "no_data",
        metrics=[RetrievalMetric(label="avg vectors / request", value=_fmt_num(avg))],
    )


def _keyword_node() -> RetrievalPipelineNode:
    # Keyword-only candidate lists are not separately observable in a single hybrid call;
    # the node documents the stage so the topology is complete.
    return RetrievalPipelineNode(
        id="keyword",
        label="Keyword (BM25)",
        sublabel="lexical match",
        group="hybrid",
        provider=_AZURE,
        status="no_data",
        description="Lexical/BM25 arm of hybrid search. Runs inside the Azure AI Search "
        "query; its candidate list is fused by RRF and not separately logged.",
    )


def _vector_node() -> RetrievalPipelineNode:
    return RetrievalPipelineNode(
        id="vector",
        label="Vector (ANN)",
        sublabel="embedding similarity",
        group="hybrid",
        provider=_AZURE,
        status="no_data",
        description="Approximate-nearest-neighbour arm of hybrid search. Runs inside the "
        "Azure AI Search query; fused by RRF and not separately logged.",
    )


def _rrf_node(rag: list[RagPipelineView]) -> RetrievalPipelineNode:
    n = len(rag)
    no_results = sum(
        1
        for p in rag
        if p.counts.found == 0 or (p.search is not None and p.search.has_results is False)
    )
    zero_rate = _rate(no_results, n)
    broadened = sum(1 for p in rag if p.search is not None and p.search.broadened)
    broaden_rate = _rate(broadened, n)
    found = [float(p.counts.found) for p in rag]
    calls = [float(p.search.search_call_count) for p in rag if p.search and p.search.search_call_count is not None]
    return RetrievalPipelineNode(
        id="rrf",
        label="RRF Fusion",
        sublabel="hybrid search",
        group="hybrid",
        provider=_AZURE,
        description="Reciprocal-rank-fuses the keyword and vector candidate lists into one "
        "ranked set — this fusion is what 'hybrid search' refers to.",
        metrics=[
            RetrievalMetric(
                label="zero-result rate", value=_fmt_pct(zero_rate),
                tone=_zero_result_tone(zero_rate),
                hint="requests where hybrid search returned nothing usable",
            ),
            RetrievalMetric(label="avg candidates found", value=_fmt_num(_safe_mean(found))),
            RetrievalMetric(
                label="broadened", value=_fmt_pct(broaden_rate),
                tone="warn" if (broaden_rate or 0) > 0.15 else "muted",
                hint="requests that fell back to a broadened re-search",
            ),
            RetrievalMetric(label="avg search calls", value=_fmt_num(_safe_mean(calls))),
        ],
    )


def _rerank_node(rag: list[RagPipelineView]) -> RetrievalPipelineNode:
    rerank_logged = sum(
        1 for p in rag if any(s.reranker_score is not None for s in p.sources)
    )
    # Rank churn: among requests whose sources carry both pre- and post-rerank ranks,
    # how much the reranker reshuffled the order.
    churn_shares: list[float] = []
    lead_changes = 0
    lead_total = 0
    for p in rag:
        ranked = [s for s in p.sources if s.rank_before is not None and s.rank_after is not None]
        if len(ranked) < 2:
            continue
        changed = sum(1 for s in ranked if s.rank_before != s.rank_after)
        churn_shares.append(changed / len(ranked))
        lead_total += 1
        before_lead = min(ranked, key=lambda s: s.rank_before)
        after_lead = min(ranked, key=lambda s: s.rank_after)
        if (before_lead.url or before_lead.title) != (after_lead.url or after_lead.title):
            lead_changes += 1

    if rerank_logged == 0:
        return RetrievalPipelineNode(
            id="rerank",
            label="Semantic Reranker",
            sublabel="L2 · cross-encoder",
            provider=_AZURE,
            status="no_data",
            description="Azure AI Search semantic ranker (L2). A distinct stage from hybrid "
            "search: it re-scores the top hybrid results with a cross-encoder. No reranker "
            "scores were logged on these traces, so its effect can't be measured yet.",
        )

    avg_churn = _safe_mean(churn_shares)
    lead_rate = _rate(lead_changes, lead_total)
    return RetrievalPipelineNode(
        id="rerank",
        label="Semantic Reranker",
        sublabel="L2 · cross-encoder",
        provider=_AZURE,
        description="Azure AI Search semantic ranker (L2) — a distinct stage from hybrid "
        "search that re-scores the top hybrid results with a cross-encoder.",
        metrics=[
            RetrievalMetric(
                label="reranked requests", value=_fmt_pct(_rate(rerank_logged, len(rag))),
                hint="share of requests with reranker scores logged",
            ),
            RetrievalMetric(
                label="avg rank churn", value=_fmt_pct(avg_churn),
                hint="share of sources the reranker moved",
            ),
            RetrievalMetric(
                label="top result changed", value=_fmt_pct(lead_rate),
                tone="good" if (lead_rate or 0) > 0.2 else "muted",
                hint="requests where reranking replaced the #1 result — the reranker earning its keep",
            ),
        ],
    )


def _filter_node(rag: list[RagPipelineView]) -> RetrievalPipelineNode:
    drops: list[float] = []
    for p in rag:
        f = p.search
        if f and f.candidates_before_filter and f.kept is not None and f.candidates_before_filter > 0:
            drops.append(1 - f.kept / f.candidates_before_filter)
    if not drops:
        return RetrievalPipelineNode(
            id="score_filter",
            label="Score Filter",
            sublabel="relative + absolute floor",
            status="no_data",
            description="Drops low-score candidates (relative gap to the top hit + an absolute "
            "floor). The candidate/kept counts aren't logged on these traces yet.",
        )
    avg_drop = _safe_mean(drops)
    return RetrievalPipelineNode(
        id="score_filter",
        label="Score Filter",
        sublabel="relative + absolute floor",
        description="Drops low-score candidates by a relative gap to the top hit plus an "
        "absolute score floor.",
        metrics=[
            RetrievalMetric(
                label="avg dropped", value=_fmt_pct(avg_drop),
                tone="warn" if (avg_drop or 0) > 0.6 else "muted",
                hint="share of candidates removed before context assembly",
            ),
        ],
    )


def _context_node(rag: list[RagPipelineView]) -> RetrievalPipelineNode:
    found = [float(p.counts.found) for p in rag]
    used = [float(p.counts.used_in_context) for p in rag]
    cited = [float(p.counts.cited) for p in rag]
    return RetrievalPipelineNode(
        id="context_assembly",
        label="Context Assembly",
        sublabel="found → used → cited",
        description="Assembles the surviving sources into the prompt context for generation.",
        metrics=[
            RetrievalMetric(label="avg found", value=_fmt_num(_safe_mean(found))),
            RetrievalMetric(label="avg used", value=_fmt_num(_safe_mean(used))),
            RetrievalMetric(label="avg cited", value=_fmt_num(_safe_mean(cited))),
        ],
    )


def _generation_node(rag: list[RagPipelineView]) -> RetrievalPipelineNode:
    tokens = [float(p.answer_tokens_out) for p in rag if p.answer_tokens_out is not None]
    models = Counter(p.answer_model for p in rag if p.answer_model)
    top_model = models.most_common(1)[0][0] if models else None
    metrics = [RetrievalMetric(label="avg output tokens", value=_fmt_num(_safe_mean(tokens), 0))]
    if top_model:
        metrics.append(RetrievalMetric(label="model", value=top_model, tone="muted"))
    return RetrievalPipelineNode(
        id="generation",
        label="LLM Generation",
        sublabel="grounded answer",
        description="Generates the answer from the assembled context.",
        status="active" if (tokens or top_model) else "no_data",
        metrics=metrics,
    )


def _judge_node(rag: list[RagPipelineView]) -> RetrievalPipelineNode:
    judged = [p for p in rag if p.judge is not None and p.judge.passed is not None]
    if not judged:
        return RetrievalPipelineNode(
            id="judge",
            label="Grounding Judge",
            sublabel="faithfulness check",
            status="no_data",
            description="Post-hoc check that the answer is grounded in the retrieved sources. "
            "No judge verdicts were logged on these traces.",
        )
    passed = sum(1 for p in judged if p.judge.passed)
    pass_rate = _rate(passed, len(judged))
    avg_corr = _safe_mean([float(len(p.judge.corrections)) for p in judged])
    return RetrievalPipelineNode(
        id="judge",
        label="Grounding Judge",
        sublabel="faithfulness check",
        description="Post-hoc check that the answer is grounded in the retrieved sources.",
        metrics=[
            RetrievalMetric(
                label="pass rate", value=_fmt_pct(pass_rate), tone=_pass_tone(pass_rate),
                hint="share of answers the grounding judge passed",
            ),
            RetrievalMetric(label="avg corrections", value=_fmt_num(avg_corr)),
        ],
    )
