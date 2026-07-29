"""Tests for the Cohere cross-encoder rerank head (services/cohere_rerank.py + its pool passes)."""

from __future__ import annotations

import httpx
import pytest

from app.index_providers.base import CorpusDoc
from app.services.chunk_pool import AgenticQuery, assemble_pool
from app.services.chunk_labeling import build_pool_view
from app.services.chunk_pool_merge import PooledChunk, PoolResult
from app.services.cohere_rerank import (
    AGENTIC_COHERE_STAGE,
    AUTH_API_KEY,
    COHERE_STAGE,
    CohereRerankConfig,
    CohereRerankError,
    get_cohere_rerank_config,
    rerank_documents,
)
from app.services.retrieval_metrics_aggregate import (
    RERANK_SCALE_MAX,
    STAGE_LABELS,
    ranked_chunks_for_head,
    rerank_thresholds_for,
)

CONFIG = CohereRerankConfig(
    endpoint="https://rr.eastus.models.ai.azure.com",
    api_key="secret",
    model="rerank-v3.5",
)


def _doc(cid, **kw):
    return CorpusDoc(id=cid, **kw)


# --- Config resolution -----------------------------------------------------------------------


def test_config_none_without_endpoint_or_key():
    assert get_cohere_rerank_config(None) is None
    assert get_cohere_rerank_config({"cohere_rerank_endpoint": "https://x"}) is None
    assert get_cohere_rerank_config({"cohere_rerank_key": "k"}) is None


def test_project_settings_resolve_config_with_defaults():
    config = get_cohere_rerank_config(
        {"cohere_rerank_endpoint": " https://x/ ", "cohere_rerank_key": " k "}
    )
    assert config is not None
    assert config.endpoint == "https://x/"
    assert config.api_key == "k"
    assert config.model == "rerank-v3.5"
    assert config.pool_candidates is False


def test_url_appends_route_unless_already_present():
    assert CONFIG.url == "https://rr.eastus.models.ai.azure.com/v2/rerank"
    explicit = CohereRerankConfig(endpoint="https://x/v1/rerank", api_key="k", model="m")
    assert explicit.url == "https://x/v1/rerank"


# --- Wire protocol ---------------------------------------------------------------------------


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_rerank_maps_scores_back_to_chunk_ids():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={"results": [{"index": 1, "relevance_score": 0.91}, {"index": 0, "relevance_score": 0.12}]},
        )

    async with _client(handler) as client:
        scores = await rerank_documents(
            client, CONFIG, "die frage", [("a", "text a"), ("b", "text b")]
        )
    assert scores == {"b": 0.91, "a": 0.12}
    assert seen["model"] == "rerank-v3.5"
    assert seen["documents"] == ["text a", "text b"]
    assert seen["auth"] == "Bearer secret"


@pytest.mark.asyncio
async def test_documents_without_text_are_dropped_before_the_call():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert body["documents"] == ["only text"]
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.5}]})

    async with _client(handler) as client:
        scores = await rerank_documents(
            client, CONFIG, "q", [("empty", "   "), ("has", "only text")]
        )
    assert scores == {"has": 0.5}


@pytest.mark.asyncio
async def test_no_call_when_every_document_lacks_text():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("reranker called with no scorable documents")

    async with _client(handler) as client:
        assert await rerank_documents(client, CONFIG, "q", [("a", "")]) == {}


@pytest.mark.asyncio
async def test_bearer_rejection_retries_with_api_key_header():
    attempts: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.headers.get("api-key") or request.headers.get("Authorization"))
        if "api-key" not in request.headers:
            return httpx.Response(401, text="unauthorized")
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.7}]})

    async with _client(handler) as client:
        scores = await rerank_documents(client, CONFIG, "q", [("a", "text")])
    assert scores == {"a": 0.7}
    assert attempts == ["Bearer secret", "secret"]


@pytest.mark.asyncio
async def test_explicit_auth_style_is_not_retried():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(403, text="forbidden")

    explicit = CohereRerankConfig(
        endpoint="https://x", api_key="k", model="m", auth=AUTH_API_KEY, auth_explicit=True
    )
    async with _client(handler) as client:
        with pytest.raises(CohereRerankError):
            await rerank_documents(client, explicit, "q", [("a", "text")])
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_http_error_raises_rerank_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with _client(handler) as client:
        with pytest.raises(CohereRerankError, match="500"):
            await rerank_documents(client, CONFIG, "q", [("a", "text")])


# --- Pool passes -----------------------------------------------------------------------------


class QueryAwareProvider:
    """Provider returning canned hits per (query, mode), so base and agentic queries differ."""

    def __init__(self, by_query_mode: dict[tuple[str, str], list[CorpusDoc]]):
        self._by = by_query_mode

    async def search_documents(self, query, n, filters=None, *, mode="keyword", query_vector=None):
        return self._by.get((query, mode), [])[:n]


def _score_handler(scores_by_text: dict[str, float]):
    """Handler scoring each document by a lookup on its text, so order is asserted explicitly."""

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        docs = json.loads(request.content)["documents"]
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": i, "relevance_score": scores_by_text.get(t, 0.0)}
                    for i, t in enumerate(docs)
                ]
            },
        )

    return handler


@pytest.mark.asyncio
async def test_cohere_head_rescores_the_hybrid_window():
    provider = QueryAwareProvider(
        {
            ("base", "keyword"): [_doc("k1", snippet="kw text")],
            ("base", "hybrid"): [
                _doc("h1", snippet="weak", score=0.03),
                _doc("h2", snippet="strong", score=0.02),
            ],
        }
    )
    async with _client(_score_handler({"weak": 0.1, "strong": 0.88})) as client:
        res = await assemble_pool(
            provider, "base", modes=["keyword"], cohere=CONFIG, http_client=client
        )
    by_id = {c.chunk_id: c for c in res.chunks}
    assert by_id["h2"].rerank_scores[COHERE_STAGE] == 0.88
    assert by_id["h1"].rerank_scores[COHERE_STAGE] == 0.1
    # Score-only: the rerank pass must not hand out positional ranks.
    assert by_id["h2"].ranks == {}
    assert COHERE_STAGE in res.heads_ran
    # The reranker's ordering flips the hybrid order, which is the whole point of the stage.
    assert [c.chunk_id for c in ranked_chunks_for_head(res.chunks, COHERE_STAGE)] == ["h2", "h1"]


@pytest.mark.asyncio
async def test_agentic_cohere_scores_agentic_union_against_the_base_question():
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        asked.append(body["query"])
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": i, "relevance_score": 0.9 if t == "late best" else 0.2}
                    for i, t in enumerate(body["documents"])
                ]
            },
        )

    provider = QueryAwareProvider(
        {
            ("base", "keyword"): [_doc("b1", snippet="base hit")],
            ("sub-a", "keyword"): [_doc("a1", snippet="early mediocre")],
            ("sub-b", "keyword"): [_doc("a2", snippet="late best")],
        }
    )
    async with _client(handler) as client:
        res = await assemble_pool(
            provider,
            "base",
            modes=["keyword"],
            agentic_queries=[AgenticQuery("sub-a"), AgenticQuery("sub-b")],
            cohere=CONFIG,
            http_client=client,
        )
    by_id = {c.chunk_id: c for c in res.chunks}
    # The later sub-query's better chunk outranks the earlier one's, which the positional
    # (first-wins) agentic union cannot do: a1 is agentic #1, a2 only #1 of its own sub-query.
    ranked = [c.chunk_id for c in ranked_chunks_for_head(res.chunks, AGENTIC_COHERE_STAGE)]
    assert ranked[0] == "a2"
    assert by_id["a2"].rerank_scores[AGENTIC_COHERE_STAGE] == 0.9
    # Both passes rerank against the user's real question, never a sub-query.
    assert set(asked) == {"base"}
    assert AGENTIC_COHERE_STAGE in res.heads_ran
    # A base-only chunk was never an agentic candidate, so this head leaves it unscored.
    assert AGENTIC_COHERE_STAGE not in by_id["b1"].rerank_scores


@pytest.mark.asyncio
async def test_agentic_cohere_skipped_without_agentic_queries():
    provider = QueryAwareProvider(
        {("base", "keyword"): [_doc("b1", snippet="t")], ("base", "hybrid"): [_doc("b1", snippet="t")]}
    )
    async with _client(_score_handler({"t": 0.5})) as client:
        res = await assemble_pool(
            provider, "base", modes=["keyword"], cohere=CONFIG, http_client=client
        )
    assert AGENTIC_COHERE_STAGE not in res.heads_ran


@pytest.mark.asyncio
async def test_rerank_failure_is_reported_not_fatal():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    provider = QueryAwareProvider(
        {
            ("base", "keyword"): [_doc("k1", snippet="kw")],
            ("base", "hybrid"): [_doc("h1", snippet="hy")],
        }
    )
    async with _client(handler) as client:
        res = await assemble_pool(
            provider, "base", modes=["keyword"], cohere=CONFIG, http_client=client
        )
    # The pool still holds the index heads' candidates; only the Cohere head is marked failed.
    assert [c.chunk_id for c in res.chunks] == ["k1"]
    assert COHERE_STAGE not in res.heads_ran
    assert "429" in res.heads_failed[COHERE_STAGE]


@pytest.mark.asyncio
async def test_no_cohere_config_leaves_pool_untouched():
    provider = QueryAwareProvider({("base", "keyword"): [_doc("k1", snippet="kw")]})
    res = await assemble_pool(provider, "base", modes=["keyword"])
    assert res.heads_ran == ["keyword"]
    assert all(not c.rerank_scores for c in res.chunks)


# --- Stage plumbing --------------------------------------------------------------------------


def test_both_cohere_stages_are_registered_next_to_their_azure_counterpart():
    heads = [h for h, _ in STAGE_LABELS]
    assert heads.index(COHERE_STAGE) == heads.index("semantic") + 1
    assert heads.index(AGENTIC_COHERE_STAGE) == heads.index("agentic_rerank") + 1
    assert RERANK_SCALE_MAX[COHERE_STAGE] == 1.0
    assert RERANK_SCALE_MAX["agentic_rerank"] == 4.0


def test_threshold_grid_spans_each_scale():
    azure = rerank_thresholds_for(4.0)
    cohere = rerank_thresholds_for(1.0)
    assert (azure[0], azure[-1]) == (0.0, 4.0)
    assert (cohere[0], cohere[-1]) == (0.0, 1.0)
    assert len(azure) == len(cohere)


def test_pool_view_orders_by_cohere_score_when_scored():
    # Cohere scored two chunks; a third was only found positionally. Scored chunks lead by score,
    # the unscored one still appears (nothing is hidden from the labeler).
    low = PooledChunk(chunk_id="low", ranks={"semantic": 1}, rerank_scores={COHERE_STAGE: 0.2})
    high = PooledChunk(chunk_id="high", ranks={"keyword": 9}, rerank_scores={COHERE_STAGE: 0.95})
    unscored = PooledChunk(chunk_id="unscored", ranks={"hybrid": 1})
    view = build_pool_view(
        "t1",
        "q",
        PoolResult(chunks=[low, high, unscored]),
        provider_connected=True,
        labels_by_key={},
    )
    assert [c.chunk_id for c in view.chunks] == ["high", "low", "unscored"]
    assert view.chunks[0].rerank_scores == {COHERE_STAGE: 0.95}
