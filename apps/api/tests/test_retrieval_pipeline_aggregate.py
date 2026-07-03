"""Tests for the aggregate retrieval pipeline flow chart
(services/retrieval_pipeline_aggregate.py).

Builds small synthetic RAG traces and checks the fixed topology, the rolled-up node
stats, and that stages with no logged signal surface as ``no_data`` rather than zeros.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.models.models import Span, SpanType, Trace, TraceStatus
from app.services.retrieval_config import RAG_SPAN_NAME_DEFAULTS
from app.services.retrieval_pipeline_aggregate import build_retrieval_pipeline_aggregate

SELECTED_URL = "https://rde.example/wiki/pages/1"
OTHER_URL = "https://rde.example/wiki/pages/2"


def _span(name, type_, **kw):
    return Span(id=uuid4(), trace_id=uuid4(), name=name, type=type_, **kw)


def _rag_trace(*, has_results=True, broadened=False, reranked=True, passed=True) -> Trace:
    trace = Trace(
        id=uuid4(),
        integration_id=uuid4(),
        external_id=f"trace-{uuid4()}",
        name="chat-completion",
        start_time=datetime(2026, 6, 18, tzinfo=timezone.utc),
        status=TraceStatus.success,
        trace_metadata={},
    )
    search = _span(
        "mandatory-search",
        SpanType.chain,
        input={"queries": ["q one", "q two", "q three"]},
        output={
            "searchCallCount": 4,
            "chunkResults": 5 if has_results else 0,
            "hasResults": has_results,
            "broadened": broadened,
        },
    )
    chunk_b = {"tool_name": "chunks", "title": "B", "url": SELECTED_URL, "score": 5.0}
    chunk_c = {"tool_name": "chunks", "title": "C", "url": OTHER_URL, "score": 4.0}
    if reranked:
        # C ranks higher pre-rerank, B wins post-rerank → reranker reshuffles the lead.
        chunk_b |= {"originalScore": 0.01, "rerankerScore": 5.0, "scoreScale": "reranker"}
        chunk_c |= {"originalScore": 0.03, "rerankerScore": 4.0, "scoreScale": "reranker"}
    retrieval = _span(
        "retrieval-context",
        SpanType.chain,
        output={"sources": [chunk_b, chunk_c] if has_results else []},
    )
    generation = _span(
        "llm-generation",
        SpanType.llm,
        input={
            "messages": [
                {
                    "role": "user",
                    "content": f"Q\n\nSUCHERGEBNISSE AUS DER WISSENSDATENBANK:\n[1] B\nQuelle: {SELECTED_URL}",
                }
            ]
        },
        output="Answer [1]",
        tokens_in=100,
        tokens_out=42,
        model="gpt-5.4",
    )
    judge = _span(
        "response-judge-llm",
        SpanType.llm,
        input={"prompt": f"RESPONSE:\nAnswer [1]\n\nSOURCE_ORDER:\n[1] = {SELECTED_URL}"},
        output={"passed": passed, "corrections": []},
    )
    trace.spans = [search, retrieval, generation, judge]
    return trace


def _node(resp, node_id):
    return next(n for n in resp.nodes if n.id == node_id)


def _metric(node, label):
    return next(m for m in node.metrics if m.label == label)


def test_empty_when_no_rag_traces():
    plain = Trace(id=uuid4(), integration_id=uuid4(), name="x", start_time=None, spans=[])
    resp = build_retrieval_pipeline_aggregate([plain], dict(RAG_SPAN_NAME_DEFAULTS))
    assert resp.available is False
    assert resp.rag_traces == 0


def test_fixed_topology_and_hybrid_separation():
    resp = build_retrieval_pipeline_aggregate([_rag_trace()], dict(RAG_SPAN_NAME_DEFAULTS))
    assert resp.available is True
    ids = {n.id for n in resp.nodes}
    # Hybrid arms, RRF fusion and the reranker are distinct nodes.
    assert {"keyword", "vector", "rrf", "rerank"} <= ids
    # All Azure-hosted stages carry the provider; reranker is separate from the hybrid group.
    assert _node(resp, "rrf").group == "hybrid"
    assert _node(resp, "rrf").provider == "Azure AI Search"
    assert _node(resp, "rerank").group is None
    assert _node(resp, "rerank").provider == "Azure AI Search"
    # Edges fan keyword+vector into RRF then into the reranker.
    pairs = {(e.source, e.target) for e in resp.edges}
    assert ("keyword", "rrf") in pairs
    assert ("vector", "rrf") in pairs
    assert ("rrf", "rerank") in pairs
    # Broadening re-runs the hybrid search (same queries, filters dropped), so the fallback
    # loops back to RRF — not to keyword-only or to query expansion.
    assert ("score_filter", "rrf") in {
        (e.source, e.target) for e in resp.edges if e.kind == "fallback"
    }


def test_rollup_stats():
    traces = [
        _rag_trace(passed=True),
        _rag_trace(passed=False),
        _rag_trace(has_results=False, passed=False),
    ]
    resp = build_retrieval_pipeline_aggregate(traces, dict(RAG_SPAN_NAME_DEFAULTS))
    assert resp.rag_traces == 3

    # One of three returned nothing usable.
    assert _metric(_node(resp, "rrf"), "zero-result rate").value == "33%"
    # Judge passed on 1 of the 3 judged requests.
    assert _metric(_node(resp, "judge"), "pass rate").value == "33%"
    # Reranker reshuffled the lead on the requests that had results.
    assert _metric(_node(resp, "rerank"), "top result changed").value != "—"


def test_no_data_when_signal_absent():
    resp = build_retrieval_pipeline_aggregate(
        [_rag_trace(reranked=False)], dict(RAG_SPAN_NAME_DEFAULTS)
    )
    # No reranker scores logged → the stage is shown but marked no_data.
    assert _node(resp, "rerank").status == "no_data"
    # Score-drop funnel isn't logged by default → filter node is no_data too.
    assert _node(resp, "score_filter").status == "no_data"
