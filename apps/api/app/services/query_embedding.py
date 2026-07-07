"""Embed a query into a vector, so LoopLM can run real vector/hybrid search itself.

Azure AI Search's text-based vector query (`VectorizableTextQuery`) only works when the index
declares a server-side *vectorizer*. Many indexes (e.g. rde-gpt's) hold embeddings but have no
query-time vectorizer, so we embed the query here and send a raw vector instead.

The embedder reuses the project's analysis-LLM Azure OpenAI / OpenAI credentials (see
:mod:`app.services.analysis_llm`) plus a dedicated embedding deployment/model. The model and
dimensions MUST match whatever built the index's vector field, or the nearest-neighbour search
is meaningless. When nothing is configured, :func:`build_query_embedder` returns ``None`` and the
caller falls back to text-based vector search (or leaves the head unavailable).
"""

from __future__ import annotations

import logging

from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class QueryEmbedder:
    """Embeds query text with a configured OpenAI/Azure OpenAI embedding model."""

    def __init__(self, client: AsyncOpenAI | AsyncAzureOpenAI, model: str, dimensions: int | None):
        self._client = client
        self._model = model
        self._dimensions = dimensions

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, text: str) -> list[float]:
        kwargs: dict = {"model": self._model, "input": text}
        # `dimensions` is only honoured by text-embedding-3* models; pass it when set.
        if self._dimensions:
            kwargs["dimensions"] = self._dimensions
        resp = await self._client.embeddings.create(**kwargs)
        return list(resp.data[0].embedding)

    async def aclose(self) -> None:
        await self._client.close()


def build_query_embedder(merged_settings: dict | None) -> QueryEmbedder | None:
    """Build a query embedder from merged analysis-LLM settings, or None if not configured.

    ``merged_settings`` is the dict produced by ``merge_llm_settings`` (project over user). The
    embedding provider follows the analysis-LLM provider; embedding deployment/model and
    dimensions come from dedicated keys (falling back to env defaults in :class:`Settings`).
    """
    s = merged_settings or {}
    provider = s.get("llm_provider") or settings.analysis_llm_provider
    dimensions = s.get("embedding_dimensions") or settings.embedding_dimensions
    dims = int(dimensions) if dimensions else None

    if provider == "azure_openai":
        api_key = s.get("azure_openai_api_key") or settings.azure_openai_api_key
        endpoint = s.get("azure_openai_endpoint") or settings.azure_openai_endpoint
        deployment = (
            s.get("azure_openai_embedding_deployment") or settings.azure_openai_embedding_deployment
        )
        if not (api_key and endpoint and deployment):
            return None
        api_version = s.get("azure_openai_api_version") or settings.azure_openai_api_version
        client = AsyncAzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
            timeout=60.0,
            max_retries=settings.model_max_retries,
        )
        return QueryEmbedder(client, deployment, dims)

    # openai
    api_key = s.get("openai_api_key") or settings.openai_api_key
    model = s.get("openai_embedding_model") or settings.openai_embedding_model
    if not (api_key and model):
        return None
    return QueryEmbedder(
        AsyncOpenAI(api_key=api_key, timeout=60.0, max_retries=settings.model_max_retries),
        model,
        dims,
    )


async def embed_query_with(embedder: QueryEmbedder | None, query: str) -> list[float] | None:
    """Embed ``query`` with an already-built embedder, or None. Never raises.

    Lets a caller build the embedder once and reuse it across many queries (the probe path),
    instead of constructing and tearing down a client per call. A failed or absent embedder
    returns None so callers fall back to text-based vector search (or keyword-only).
    """
    if embedder is None or not query.strip():
        return None
    try:
        return await embedder.embed(query)
    except Exception:  # noqa: BLE001 — embedding is best-effort; degrade to no-vector search
        logger.warning("Query embedding failed; falling back to non-vector search", exc_info=True)
        return None


async def embed_query(merged_settings: dict | None, query: str) -> list[float] | None:
    """Embed ``query`` if an embedder is configured, else None. Never raises.

    A failed or unconfigured embedding returns None so callers fall back to text-based vector
    search (or keyword-only) instead of breaking the whole pool/probe. Builds and closes a
    one-shot client; for many queries prefer :func:`build_query_embedder` +
    :func:`embed_query_with` to reuse one client.
    """
    if not query.strip():
        return None
    embedder = build_query_embedder(merged_settings)
    if embedder is None:
        return None
    try:
        return await embed_query_with(embedder, query)
    finally:
        await embedder.aclose()
