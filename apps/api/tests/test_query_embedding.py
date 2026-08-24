"""Tests for the query embedder and the Azure raw-vector search path."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services import query_embedding
from app.services.query_embedding import build_query_embedder, embed_query


def test_build_query_embedder_none_when_unconfigured():
    # OpenAI provider but no API key (env default is empty) → no embedder.
    assert build_query_embedder({"llm_provider": "openai"}) is None
    # Azure provider missing the embedding deployment → no embedder.
    assert (
        build_query_embedder(
            {
                "llm_provider": "azure_openai",
                "azure_openai_api_key": "k",
                "azure_openai_endpoint": "https://x.openai.azure.com",
            }
        )
        is None
    )


def test_build_query_embedder_openai_configured():
    emb = build_query_embedder({"llm_provider": "openai", "openai_api_key": "sk-test"})
    assert emb is not None
    assert emb._model == "text-embedding-3-large"  # env default
    assert emb._dimensions == 3072  # env default


def test_build_query_embedder_azure_configured():
    emb = build_query_embedder(
        {
            "llm_provider": "azure_openai",
            "azure_openai_api_key": "k",
            "azure_openai_endpoint": "https://x.openai.azure.com",
            "azure_openai_embedding_deployment": "embed-3-large",
            "embedding_dimensions": 1536,
        }
    )
    assert emb is not None
    assert emb._model == "embed-3-large"  # azure passes the deployment as the model
    assert emb._dimensions == 1536


# --- Cohere embedding backend ---


def test_build_query_embedder_cohere_selected_by_embedding_provider():
    """``embedding_provider`` overrides the analysis-LLM provider, which stays OpenAI."""
    from app.services.query_embedding import CohereQueryEmbedder

    emb = build_query_embedder(
        {
            "llm_provider": "azure_openai",
            "embedding_provider": "cohere",
            "cohere_embed_endpoint": "https://r.services.ai.azure.com",
            "cohere_embed_key": "k",
            "cohere_embed_model": "embed-v-4-0",
            "embedding_dimensions": 1536,
        }
    )
    assert isinstance(emb, CohereQueryEmbedder)
    assert emb.model == "embed-v-4-0"
    # The Foundry route the deployment actually serves, appended to the bare resource URL.
    assert emb.url == "https://r.services.ai.azure.com/providers/cohere/v2/embed"


def test_build_query_embedder_cohere_none_when_half_configured():
    # A key without an endpoint is not a usable backend; leave vector search off rather than
    # failing per query.
    assert (
        build_query_embedder({"embedding_provider": "cohere", "cohere_embed_key": "k"}) is None
    )


def test_cohere_embed_url_uses_configured_route_verbatim():
    from app.services.query_embedding import CohereQueryEmbedder

    emb = CohereQueryEmbedder("https://api.cohere.com/v2/embed", "k", "embed-v-4-0", 1536)
    assert emb.url == "https://api.cohere.com/v2/embed"


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeHttpClient:
    """Records requests and replays queued responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.closed = False

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_cohere_embed_sends_query_input_type_and_parses_v2_shape():
    from app.services.query_embedding import CohereQueryEmbedder

    http = _FakeHttpClient([_FakeResponse(200, {"embeddings": {"float": [[0.1, 0.2, 0.3]]}})])
    emb = CohereQueryEmbedder("https://r.services.ai.azure.com", "k", "embed-v-4-0", 3, client=http)

    assert await emb.embed("wie geht das?") == [0.1, 0.2, 0.3]
    body = http.calls[0]["json"]
    # Cohere embeddings are asymmetric — a document input_type here would score a document
    # vector against the corpus.
    assert body["input_type"] == "search_query"
    assert body["texts"] == ["wie geht das?"]
    assert body["output_dimension"] == 3
    assert http.calls[0]["headers"]["api-key"] == "k"


@pytest.mark.asyncio
async def test_cohere_embed_falls_back_to_bearer_auth_on_401():
    """Foundry takes api-key, Cohere's own API takes Bearer; unset tries both."""
    from app.services.query_embedding import CohereQueryEmbedder

    http = _FakeHttpClient(
        [
            _FakeResponse(401, text="unauthorized"),
            _FakeResponse(200, {"embeddings": [[0.5, 0.6]]}),  # v1 response shape
        ]
    )
    emb = CohereQueryEmbedder("https://api.cohere.com", "k", "embed-v-4-0", None, client=http)

    assert await emb.embed("q") == [0.5, 0.6]
    assert "api-key" in http.calls[0]["headers"]
    assert http.calls[1]["headers"]["Authorization"] == "Bearer k"


@pytest.mark.asyncio
async def test_cohere_embed_rejects_dimension_mismatch():
    """The mismatch is named here rather than surfacing as an opaque search-backend 400 —
    or, worse, as a silently wrong ranking."""
    from app.services.query_embedding import CohereQueryEmbedder

    http = _FakeHttpClient([_FakeResponse(200, {"embeddings": {"float": [[0.1, 0.2]]}})])
    emb = CohereQueryEmbedder("https://r.services.ai.azure.com", "k", "m", 1536, client=http)

    with pytest.raises(RuntimeError, match="expected 1536"):
        await emb.embed("q")


@pytest.mark.asyncio
async def test_cohere_embed_batch_preserves_order_and_closes():
    from app.services.query_embedding import CohereQueryEmbedder

    http = _FakeHttpClient([_FakeResponse(200, {"embeddings": {"float": [[0.1], [0.2]]}})])
    emb = CohereQueryEmbedder("https://r.services.ai.azure.com", "k", "m", 1, client=http)

    assert await emb.embed_batch(["a", "b"]) == [[0.1], [0.2]]
    assert http.calls[0]["json"]["texts"] == ["a", "b"]
    await emb.aclose()
    assert http.closed is True


@pytest.mark.asyncio
async def test_embed_query_returns_none_when_no_embedder():
    # Unconfigured → None, no exception.
    assert await embed_query({"llm_provider": "openai"}, "what is X?") is None


@pytest.mark.asyncio
async def test_embed_query_success_and_failure(monkeypatch):
    closed = {"n": 0}

    class _FakeEmbedder:
        def __init__(self, ok):
            self._ok = ok

        async def embed(self, text):
            if not self._ok:
                raise RuntimeError("boom")
            return [0.1, 0.2, 0.3]

        async def aclose(self):
            closed["n"] += 1

    monkeypatch.setattr(query_embedding, "build_query_embedder", lambda s: _FakeEmbedder(True))
    assert await embed_query({}, "q") == [0.1, 0.2, 0.3]

    # A failing embed degrades to None (caller falls back), and the client is still closed.
    monkeypatch.setattr(query_embedding, "build_query_embedder", lambda s: _FakeEmbedder(False))
    assert await embed_query({}, "q") is None
    assert closed["n"] == 2  # closed on both the success and failure paths


# --- Azure raw-vector search path ---

def _azure_provider():
    from app.index_providers.azure_search import AzureSearchIndexProvider, _FieldInfo

    p = AzureSearchIndexProvider(
        endpoint="https://x.search.windows.net", api_key="k", index_name="idx"
    )
    # Bypass the network: a vector field + a key field.
    p._fields = {
        "id": _FieldInfo("id", "Edm.String", False, True),
        "chunk_text_vector": _FieldInfo("chunk_text_vector", "Collection(Edm.Single)", False, False),
    }
    return p


class _FakeResults:
    def __init__(self, docs):
        self._docs = docs

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d

        return gen()


@pytest.mark.asyncio
async def test_vector_search_uses_vectorized_query_when_vector_given(monkeypatch):
    from azure.search.documents.models import VectorizableTextQuery, VectorizedQuery

    p = _azure_provider()
    captured: dict = {}

    class _FakeClient:
        async def search(self, **kwargs):
            captured.update(kwargs)
            return _FakeResults([{"id": "c1", "@search.score": 1.0}])

    p._search_client = _FakeClient()

    # With a precomputed vector → VectorizedQuery carrying that vector.
    docs = await p.search_documents("q", 5, None, mode="vector", query_vector=[0.1, 0.2])
    assert [d.id for d in docs] == ["c1"]
    vq = captured["vector_queries"][0]
    assert isinstance(vq, VectorizedQuery) and list(vq.vector) == [0.1, 0.2]

    # Without a vector → text query (the path that needs a server-side vectorizer).
    await p.search_documents("q", 5, None, mode="vector")
    assert isinstance(captured["vector_queries"][0], VectorizableTextQuery)


@pytest.mark.asyncio
async def test_keyword_arm_is_scoped_to_the_content_field():
    """The text arm must not search every searchable field.

    An index can carry a scoring profile that weights titles and metadata above the content — on
    `prod-index-2026-08` the default profile puts `page_title` and `stichwoerter` at 3.0 and
    `chunk_text` at 1.0 — and those metadata fields are page-level, identical on every chunk of a
    page. Unscoped, a term hitting one lifts a whole page uniformly and the probe measures the
    profile rather than BM25: recall@10 28.9% unscoped against 52.2% scoped, over 90 questions.
    """
    from app.index_providers.azure_search import _FieldInfo

    p = _azure_provider()
    p._fields["chunk_text"] = _FieldInfo("chunk_text", "Edm.String", False, False, searchable=True)
    captured: dict = {}

    class _FakeClient:
        async def search(self, **kwargs):
            captured.update(kwargs)
            return _FakeResults([{"id": "c1", "@search.score": 3.0}])

    p._search_client = _FakeClient()

    await p.search_documents("Lieferantenwechsel", 5, None, mode="keyword")
    assert captured["search_fields"] == ["chunk_text"]

    # Hybrid fuses the same text arm, so it is scoped too.
    captured.clear()
    await p.search_documents("q", 5, None, mode="hybrid", query_vector=[0.1, 0.2])
    assert captured["search_fields"] == ["chunk_text"]

    # Vector-only has no text arm, so there is nothing to scope.
    captured.clear()
    await p.search_documents("q", 5, None, mode="vector", query_vector=[0.1, 0.2])
    assert "search_fields" not in captured


@pytest.mark.asyncio
async def test_keyword_arm_unscoped_when_no_text_field_is_recognisable():
    """No recognisable content field means the previous behaviour, not an empty query."""
    p = _azure_provider()
    captured: dict = {}

    class _FakeClient:
        async def search(self, **kwargs):
            captured.update(kwargs)
            return _FakeResults([])

    p._search_client = _FakeClient()
    await p.search_documents("q", 5, None, mode="keyword")
    assert "search_fields" not in captured


@pytest.mark.asyncio
async def test_semantic_mode_requires_config_then_sets_query_type():
    p = _azure_provider()
    captured: dict = {}

    class _FakeClient:
        async def search(self, **kwargs):
            captured.update(kwargs)
            return _FakeResults([{"id": "c1", "@search.reranker_score": 2.5}])

    p._search_client = _FakeClient()

    # No semantic configuration on the index → the head is unavailable.
    with pytest.raises(NotImplementedError):
        await p.search_documents("q", 5, None, mode="semantic")

    # With a semantic configuration → the search sets query_type=semantic + the config name,
    # and reranks the hybrid result (search_text present; vector added when we have one).
    p._semantic_config = "default-semantic-config"
    docs = await p.search_documents("q", 5, None, mode="semantic", query_vector=[0.1, 0.2])
    assert [d.id for d in docs] == ["c1"]
    assert captured["query_type"] == "semantic"
    assert captured["semantic_configuration_name"] == "default-semantic-config"
    assert captured["search_text"] == "q"  # semantic reranks the keyword/hybrid result
    assert "vector_queries" in captured  # query_vector supplied → semantic-hybrid


# --- test-embedding endpoint ---


class _StubEmbedder:
    def __init__(self, *, model="text-embedding-3-large", fail=False):
        self._model = model
        self._fail = fail

    @property
    def model(self):
        return self._model

    async def embed(self, text):
        if self._fail:
            raise RuntimeError("401 Unauthorized")
        return [0.0, 0.1, 0.2]

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_test_embedding_endpoint_unconfigured(client: AsyncClient, auth_headers, test_project):
    resp = await client.post(
        f"/api/projects/{test_project.id}/test-embedding", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False and body["configured"] is False


# --- retrieval-readiness endpoint ---


@pytest.mark.asyncio
async def test_retrieval_readiness_unconfigured(client: AsyncClient, auth_headers, test_project):
    """No embedding model and no index → banner-driving flags all report 'not ready'."""
    resp = await client.get("/api/pipeline/retrieval-readiness", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["embedding"]["configured"] is False
    assert body["embedding"]["ok"] is False
    assert body["index_connected"] is False
    assert body["semantic_configured"] is False


@pytest.mark.asyncio
async def test_retrieval_readiness_reports_embedding_ok(
    client: AsyncClient, auth_headers, monkeypatch
):
    """A working embedding probe surfaces ok=True with the model + dimensions."""
    import app.services.retrieval_readiness as readiness

    monkeypatch.setattr(readiness, "build_query_embedder", lambda s: _StubEmbedder())
    resp = await client.get(
        "/api/pipeline/retrieval-readiness?refresh=true", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["embedding"]["ok"] is True
    assert body["embedding"]["dimensions"] == 3
    assert body["embedding"]["model"] == "text-embedding-3-large"


@pytest.mark.asyncio
async def test_test_embedding_endpoint_ok(client: AsyncClient, auth_headers, test_project, monkeypatch):
    import app.services.retrieval_readiness as readiness

    monkeypatch.setattr(readiness, "build_query_embedder", lambda s: _StubEmbedder())
    resp = await client.post(
        f"/api/projects/{test_project.id}/test-embedding", headers=auth_headers
    )
    body = resp.json()
    assert body["ok"] is True and body["dimensions"] == 3
    assert body["model"] == "text-embedding-3-large"


@pytest.mark.asyncio
async def test_test_embedding_endpoint_reports_provider_error(
    client: AsyncClient, auth_headers, test_project, monkeypatch
):
    import app.services.retrieval_readiness as readiness

    monkeypatch.setattr(readiness, "build_query_embedder", lambda s: _StubEmbedder(fail=True))
    resp = await client.post(
        f"/api/projects/{test_project.id}/test-embedding", headers=auth_headers
    )
    body = resp.json()
    assert body["ok"] is False and body["configured"] is True
    assert "401" in body["error"]
