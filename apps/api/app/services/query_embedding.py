"""Embed a query into a vector, so LoopLM can run real vector/hybrid search itself.

Azure AI Search's text-based vector query (`VectorizableTextQuery`) only works when the index
declares a server-side *vectorizer*. Many indexes (e.g. rde-gpt's) hold embeddings but have no
query-time vectorizer, so we embed the query here and send a raw vector instead.

Two embedding backends are supported, because the query vector has to come from whatever model
built the index's vector field:

* **OpenAI / Azure OpenAI** — reuses the project's analysis-LLM credentials (see
  :mod:`app.services.analysis_llm`) plus a dedicated embedding deployment/model.
* **Cohere** — a serverless Azure AI Foundry deployment or Cohere's own API, configured
  separately, for indexes built with ``embed-v-4-0`` and friends.

The model and dimensions MUST match whatever built the index's vector field, or the
nearest-neighbour search is meaningless. This is not a loud failure: a query vector of the *right
length* from the *wrong model* is accepted by Azure AI Search and scored against a space it does
not belong to, so retrieval quietly degrades to noise with no error anywhere. Hence the explicit
provider choice rather than "whatever the analysis LLM uses".

When nothing is configured, :func:`build_query_embedder` returns ``None`` and the caller falls
back to text-based vector search (or leaves the head unavailable).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx
from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# ``project.settings`` keys for the embedding backend choice and the Cohere config.
EMBEDDING_PROVIDER_KEY = "embedding_provider"
COHERE_ENDPOINT_KEY = "cohere_embed_endpoint"
COHERE_KEY_KEY = "cohere_embed_key"
COHERE_MODEL_KEY = "cohere_embed_model"
COHERE_AUTH_KEY = "cohere_embed_auth"

# ``embedding_provider`` values. Unset (or anything else) means "follow the analysis-LLM provider",
# which is what every project did before Cohere existed.
COHERE_PROVIDER = "cohere"
VALID_EMBEDDING_PROVIDERS = ("openai", "azure_openai", COHERE_PROVIDER)

# Cohere's embeddings are asymmetric: a query and a document are embedded differently, and the
# service accepts either value without complaint. The indexer used ``search_document``; anything
# other than ``search_query`` here would score a document vector against the corpus.
COHERE_QUERY_INPUT_TYPE = "search_query"

# Auth styles. Azure AI Foundry serverless deployments take ``api-key``; Cohere's own API wants
# Bearer. Unset tries the Foundry style first, then Bearer.
AUTH_API_KEY = "api-key"
AUTH_BEARER = "bearer"
VALID_AUTH = (AUTH_API_KEY, AUTH_BEARER)

_COHERE_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# One embed call per query on the probe path, with a user waiting on the result: keep the batch
# modest so a request stays well inside the service's payload limits.
_COHERE_MAX_TEXTS = 96


class QueryEmbedder(ABC):
    """Text in, vector out, in whatever space the index's vector field was built in."""

    @property
    @abstractmethod
    def model(self) -> str:
        """The model/deployment name, for readiness reporting."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """The embedding of ``text``. Raises on a failed call."""

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts in one call, preserving order."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release the underlying HTTP client."""


class OpenAIQueryEmbedder(QueryEmbedder):
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

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts in one API call, preserving order.

        The OpenAI embeddings endpoint accepts list input; callers should keep
        batches modest (≤ ~64) to stay under request-size limits.
        """
        if not texts:
            return []
        kwargs: dict = {"model": self._model, "input": texts}
        if self._dimensions:
            kwargs["dimensions"] = self._dimensions
        resp = await self._client.embeddings.create(**kwargs)
        ordered = sorted(resp.data, key=lambda d: d.index)
        return [list(d.embedding) for d in ordered]

    async def aclose(self) -> None:
        await self._client.close()


class CohereQueryEmbedder(QueryEmbedder):
    """Embeds query text with a Cohere embed deployment (Azure AI Foundry or Cohere's API).

    No SDK: it is one POST, so ``httpx`` keeps the dependency list flat — the same call shape the
    Cohere reranker uses (see :mod:`app.services.cohere_rerank`).
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        dimensions: int | None,
        *,
        auth: str | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._auth = auth if auth in VALID_AUTH else None
        self._client = client or httpx.AsyncClient(timeout=_COHERE_TIMEOUT)

    @property
    def model(self) -> str:
        return self._model

    @property
    def url(self) -> str:
        """Full embed URL. An endpoint that already names the route is used verbatim.

        The Azure AI Inference route (``/models/embeddings``) rejects this body and a bare
        ``/v2/embed`` 404s on Foundry, so the provider-scoped route is the one that works.
        """
        base = self._endpoint.rstrip("/")
        return base if base.endswith("/embed") else f"{base}/providers/cohere/v2/embed"

    def _headers(self, auth: str) -> dict[str, str]:
        if auth == AUTH_BEARER:
            return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        return {"api-key": self._api_key, "Content-Type": "application/json"}

    def _parse(self, payload: Any, expected: int) -> list[list[float]]:
        """Vectors out of an embed response, in input order.

        Accepts the v2 shape (``{"embeddings": {"float": [[...]]}}``) and the v1 shape
        (``{"embeddings": [[...]]}``).
        """
        raw = payload.get("embeddings") if isinstance(payload, dict) else None
        vectors = raw.get("float") if isinstance(raw, dict) else raw
        if not isinstance(vectors, list) or len(vectors) != expected:
            raise RuntimeError(f"Cohere embed returned no usable vectors: {str(payload)[:200]}")
        out = [[float(x) for x in v] for v in vectors]
        if self._dimensions:
            for vector in out:
                if len(vector) != self._dimensions:
                    # A vector the index cannot accept would fail at the search call anyway (or,
                    # worse, be accepted at the wrong length). Failing here names the real cause.
                    raise RuntimeError(
                        f"Cohere embed returned {len(vector)} dimensions, "
                        f"expected {self._dimensions}"
                    )
        return out

    async def _post(self, texts: list[str]) -> list[list[float]]:
        body: dict[str, Any] = {
            "model": self._model,
            "texts": texts,
            "input_type": COHERE_QUERY_INPUT_TYPE,
            "embedding_types": ["float"],
        }
        if self._dimensions:
            body["output_dimension"] = self._dimensions
        auth_styles = [self._auth] if self._auth else [AUTH_API_KEY, AUTH_BEARER]
        last_error: str | None = None
        for auth in auth_styles:
            response = await self._client.post(
                self.url, json=body, headers=self._headers(auth), timeout=_COHERE_TIMEOUT
            )
            if response.status_code in (401, 403) and auth != auth_styles[-1]:
                last_error = f"HTTP {response.status_code} with {auth} auth"
                continue
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError(
                    f"Cohere embed response was not JSON: {response.text[:200]}"
                ) from exc
            return self._parse(payload, len(texts))
        raise RuntimeError(last_error or "Cohere embed authentication failed")

    async def embed(self, text: str) -> list[float]:
        return (await self._post([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), _COHERE_MAX_TEXTS):
            out.extend(await self._post(texts[start : start + _COHERE_MAX_TEXTS]))
        return out

    async def aclose(self) -> None:
        await self._client.aclose()


def _clean(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def resolve_embedding_provider(merged_settings: dict | None) -> str:
    """Which backend embeds queries: the explicit choice, else the analysis-LLM provider."""
    s = merged_settings or {}
    explicit = (_clean(s.get(EMBEDDING_PROVIDER_KEY)) or "").lower()
    if explicit in VALID_EMBEDDING_PROVIDERS:
        return explicit
    return s.get("llm_provider") or settings.analysis_llm_provider


def _build_cohere_embedder(s: dict, dims: int | None) -> CohereQueryEmbedder | None:
    endpoint = _clean(s.get(COHERE_ENDPOINT_KEY)) or _clean(settings.cohere_embed_endpoint)
    api_key = _clean(s.get(COHERE_KEY_KEY)) or _clean(settings.cohere_embed_api_key)
    if not endpoint or not api_key:
        return None
    auth = (_clean(s.get(COHERE_AUTH_KEY)) or "").lower()
    return CohereQueryEmbedder(
        endpoint,
        api_key,
        _clean(s.get(COHERE_MODEL_KEY)) or _clean(settings.cohere_embed_model) or "embed-v-4-0",
        dims,
        auth=auth if auth in VALID_AUTH else None,
    )


def build_query_embedder(merged_settings: dict | None) -> QueryEmbedder | None:
    """Build a query embedder from merged analysis-LLM settings, or None if not configured.

    ``merged_settings`` is the dict produced by ``merge_llm_settings`` (project over user). The
    embedding backend is ``embedding_provider`` when set, else it follows the analysis-LLM
    provider; deployment/model and dimensions come from dedicated keys (falling back to env
    defaults in :class:`Settings`).
    """
    s = merged_settings or {}
    provider = resolve_embedding_provider(s)
    dimensions = s.get("embedding_dimensions") or settings.embedding_dimensions
    dims = int(dimensions) if dimensions else None

    if provider == COHERE_PROVIDER:
        return _build_cohere_embedder(s, dims)

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
        return OpenAIQueryEmbedder(client, deployment, dims)

    # openai
    api_key = s.get("openai_api_key") or settings.openai_api_key
    model = s.get("openai_embedding_model") or settings.openai_embedding_model
    if not (api_key and model):
        return None
    return OpenAIQueryEmbedder(
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
