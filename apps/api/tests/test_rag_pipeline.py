"""Tests for the agentic-RAG pipeline derivation (services/rag_pipeline.py).

Payloads mirror a real rde-gpt production trace (the gas-vs-strom negative-feedback
trace ``trace-1781786858852``): query expansion → mandatory-search → retrieval-context
→ llm-generation → response-judge-llm.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.models import Integration, Span, SpanType, Trace, TraceStatus
from app.services.rag_pipeline import build_rag_pipeline
from app.services.retrieval_config import RAG_SPAN_NAME_DEFAULTS, get_rag_span_names
from app.models.project import Project

SELECTED_URL = "https://rde.example/wiki/spaces/rdeklar/pages/332038147"
DROPPED_URL = "https://rde.example/wiki/spaces/rdeklar/pages/999999"


def _span(name, type_, **kw):
    return Span(id=uuid4(), trace_id=uuid4(), name=name, type=type_, **kw)


def _rag_trace() -> Trace:
    trace = Trace(
        id=uuid4(),
        integration_id=uuid4(),
        external_id="trace-1781786858852",
        name="chat-completion",
        start_time=datetime(2026, 6, 18, tzinfo=timezone.utc),
        status=TraceStatus.success,
        trace_metadata={"queryComplexity": "moderate", "expandedQueryCount": 3},
    )
    search = _span(
        "mandatory-search",
        SpanType.chain,
        input={
            "queries": [
                "Anlage Messlokation Zählstelle kVASy",
                "Messlokation anlegen Zählstelle MaLo Messstelle kVASy",
                "Marktlokation Messlokation Zählpunkt anlegen kVASy",
            ],
            "filters": {"filterEnabled": True},
        },
        output={
            "searchCallCount": 10,
            "summaryPages": 19,
            "chunkResults": 5,
            "hasResults": True,
            "broadened": False,
        },
    )
    retrieval = _span(
        "retrieval-context",
        SpanType.chain,
        output={
            "sources": [
                {"tool_name": "mandatory-search-summaries", "title": "Summary A", "score": 2.63},
                {"tool_name": "mandatory-search-chunks", "title": "Chunk B", "url": SELECTED_URL, "score": 5.01},
                {"tool_name": "mandatory-search-chunks", "title": "Chunk C", "url": DROPPED_URL, "score": 4.5},
            ],
            "tool_calls_used": ["mandatory-search-summaries", "mandatory-search-chunks"],
        },
    )
    generation = _span(
        "llm-generation",
        SpanType.llm,
        input={
            "messages": [
                {"role": "user", "content": "Die Anlage einer Messlokation/Zählstelle in kVASy"},
                {
                    "role": "user",
                    "content": (
                        "Frage\n\nSUCHERGEBNISSE AUS DER WISSENSDATENBANK:\n"
                        f"[1] Chunk B\nQuelle: {SELECTED_URL}\nRelevanz-Score: 5.01"
                    ),
                },
            ],
            "system": "## Role\nYou are KLARA …",
        },
        output="Die folgenden Schritte … [1]",
        tokens_in=16021,
        tokens_out=2541,
        model="gpt-5.4",
    )
    judge = _span(
        "response-judge-llm",
        SpanType.llm,
        input={
            "prompt": (
                "RESPONSE:\nDie folgenden Schritte … [1]\n\n"
                f"SOURCE_ORDER:\n[1] = {SELECTED_URL}"
            ),
            "system": "You are a grounding judge …",
        },
        output={
            "passed": False,
            "corrections": [
                {"type": "delete", "find": "21. Prüfe …", "reason": "No supporting evidence …"}
            ],
        },
    )
    trace.spans = [search, retrieval, generation, judge]
    return trace


def test_build_rag_pipeline_reconstructs_funnel():
    view = build_rag_pipeline(_rag_trace(), dict(RAG_SPAN_NAME_DEFAULTS))

    assert view.available is True
    assert len(view.queries) == 3
    assert view.query_complexity == "moderate"

    assert view.search is not None
    assert view.search.search_call_count == 10
    assert view.search.summary_pages == 19
    assert view.search.chunk_results == 5
    assert view.search.broadened is False
    # Drop-funnel fields stay empty until rde-gpt logs them.
    assert view.search.candidates_before_filter is None

    assert view.answer_model == "gpt-5.4"
    assert view.answer_tokens_in == 16021
    assert view.answer and view.answer.startswith("Die folgenden")
    assert view.assembled_context and "SUCHERGEBNISSE" in view.assembled_context

    assert view.judge is not None
    assert view.judge.passed is False
    assert len(view.judge.corrections) == 1


def test_build_rag_pipeline_infers_selected_and_cited_sources():
    view = build_rag_pipeline(_rag_trace(), dict(RAG_SPAN_NAME_DEFAULTS))

    assert view.counts.found == 3
    assert view.counts.used_in_context == 1
    assert view.counts.cited == 1

    by_title = {s.title: s for s in view.sources}
    selected = by_title["Chunk B"]
    assert selected.selected is True
    assert selected.citation_index == 1
    assert selected.selection_exact is False  # reconstructed, not explicit
    assert by_title["Chunk C"].selected is False
    assert by_title["Summary A"].selected is False  # no URL → cannot match


def test_build_rag_pipeline_prefers_explicit_selection():
    trace = _rag_trace()
    retrieval = next(s for s in trace.spans if s.name == "retrieval-context")
    # rde-gpt Phase 2: explicit per-source flags take precedence over inference.
    retrieval.output["sources"][0]["selected"] = True
    retrieval.output["sources"][0]["citationIndex"] = 2
    retrieval.output["sources"][1]["selected"] = False

    view = build_rag_pipeline(trace, dict(RAG_SPAN_NAME_DEFAULTS))

    by_title = {s.title: s for s in view.sources}
    assert by_title["Summary A"].selected is True
    assert by_title["Summary A"].citation_index == 2
    assert by_title["Summary A"].selection_exact is True
    assert by_title["Chunk B"].selected is False
    assert view.counts.used_in_context == 1


def test_build_rag_pipeline_unavailable_for_non_rag_trace():
    trace = Trace(
        id=uuid4(),
        integration_id=uuid4(),
        external_id="plain",
        name="plain",
        start_time=datetime(2026, 6, 18, tzinfo=timezone.utc),
        status=TraceStatus.success,
    )
    trace.spans = [_span("agent_chain", SpanType.chain), _span("gpt4_call", SpanType.llm)]

    view = build_rag_pipeline(trace, dict(RAG_SPAN_NAME_DEFAULTS))
    assert view.available is False
    assert view.sources == []


def test_get_rag_span_names_applies_overrides():
    project = Project(id=uuid4(), owner_id=uuid4(), name="P", settings={})
    assert get_rag_span_names(project)["search"] == "mandatory-search"

    project.settings = {"rag_span_names": {"search": "custom-search"}}
    names = get_rag_span_names(project)
    assert names["search"] == "custom-search"
    assert names["generation"] == "llm-generation"  # untouched default


@pytest.mark.asyncio
async def test_rag_pipeline_endpoint(client: AsyncClient, db_session, test_integration: Integration, auth_headers):
    """Persisted trace+spans round-trip through the endpoint (JSONB + wiring)."""
    src = _rag_trace()
    trace = Trace(
        id=uuid4(),
        integration_id=test_integration.id,
        external_id="trace-endpoint",
        name="chat-completion",
        start_time=datetime(2026, 6, 18, tzinfo=timezone.utc),
        status=TraceStatus.success,
        trace_metadata=src.trace_metadata,
    )
    db_session.add(trace)
    await db_session.flush()
    for s in src.spans:
        db_session.add(
            Span(
                id=uuid4(), trace_id=trace.id, name=s.name, type=s.type,
                input=s.input, output=s.output, model=s.model,
                tokens_in=s.tokens_in, tokens_out=s.tokens_out,
            )
        )
    await db_session.commit()

    resp = await client.get(f"/api/traces/{trace.id}/rag-pipeline", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert len(data["queries"]) == 3
    assert data["counts"]["found"] == 3
    assert data["counts"]["used_in_context"] == 1
    assert data["judge"]["passed"] is False
