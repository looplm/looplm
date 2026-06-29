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


@pytest.mark.asyncio
async def test_test_embedding_endpoint_ok(client: AsyncClient, auth_headers, test_project, monkeypatch):
    import app.routers.projects as projects_router

    monkeypatch.setattr(projects_router, "build_query_embedder", lambda s: _StubEmbedder())
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
    import app.routers.projects as projects_router

    monkeypatch.setattr(projects_router, "build_query_embedder", lambda s: _StubEmbedder(fail=True))
    resp = await client.post(
        f"/api/projects/{test_project.id}/test-embedding", headers=auth_headers
    )
    body = resp.json()
    assert body["ok"] is False and body["configured"] is True
    assert "401" in body["error"]
