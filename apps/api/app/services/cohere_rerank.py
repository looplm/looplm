"""Cohere Rerank as a cross-encoder reranking head for the retrieval pool.

The index's own reranker (Azure AI Search's L2 semantic ranker) only ever sees one query's
candidates and scores them on a 0-4 scale. A cross-encoder reranker like Cohere Rerank sees
``(query, document)`` pairs directly, so it can score candidates that came from *different*
queries on one comparable 0-1 scale. That buys two things LoopLM couldn't measure before:

* **cohere_rerank** — the base question's hybrid (RRF) candidates rescored by Cohere, which is
  the same candidate set the Azure semantic head reranks. Apples-to-apples: same input, two
  rerankers, one gold set.
* **agentic_cohere** — the whole agentic candidate union rescored against the *original*
  question in one pass. The agentic path merges several sub-queries positionally (first-wins),
  which lets an early sub-query's mediocre chunk outrank a later sub-query's best one; a global
  cross-encoder pass over the union is the direct fix, and this stage measures whether it helps.

Deployment is configurable because the same wire format is served by both Azure AI Foundry
(serverless Cohere deployments, the default here) and Cohere's own API — the endpoint, key,
model and auth header live in ``project.settings`` with an env fallback (see
:class:`~app.config.Settings`). No SDK: it's one POST, so ``httpx`` keeps the dependency list flat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Pool heads + display labels for the two Cohere stages (see the module docstring).
COHERE_STAGE = "cohere_rerank"
AGENTIC_COHERE_STAGE = "agentic_cohere"
COHERE_STAGE_LABEL = "Cohere rerank"
AGENTIC_COHERE_STAGE_LABEL = "Agentic + Cohere"

# Cohere relevance scores are normalized to 0..1 (unlike Azure's 0-4 rerankerScore), so the
# score-threshold sweep needs a different scale for these stages.
COHERE_SCORE_MAX = 1.0

# ``project.settings`` keys for the per-project Cohere config.
ENDPOINT_KEY = "cohere_rerank_endpoint"
KEY_KEY = "cohere_rerank_key"
MODEL_KEY = "cohere_rerank_model"
AUTH_KEY = "cohere_rerank_auth"
POOL_KEY = "cohere_rerank_pool"

# Auth styles: Azure AI Foundry serverless endpoints accept both, older ones only ``api-key``;
# Cohere's own API wants Bearer. Default is Bearer with a one-shot ``api-key`` retry on 401/403.
AUTH_BEARER = "bearer"
AUTH_API_KEY = "api-key"
VALID_AUTH = (AUTH_BEARER, AUTH_API_KEY)

# Candidate depth for the base-question Cohere pass: rerank the hybrid top-50, matching the window
# Azure's semantic ranker uses (see AGENTIC_RERANK_DEPTH), so the two rerank stages are comparable.
COHERE_RERANK_DEPTH = 50

# Hard cap on documents per call — our pools are tens of chunks; this is a runaway guard, well
# under the API's own 1000-document limit.
_MAX_DOCS = 250

# Per-document character cap. rerank-v3.5 allows ~4096 tokens per document; ~8k chars keeps a
# long chunk inside that without a tokenizer dependency, and the head of a chunk is what carries
# its topical signal anyway.
_MAX_DOC_CHARS = 8000

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class CohereRerankError(RuntimeError):
    """The rerank call failed (misconfigured endpoint/key, bad request, backend error)."""


@dataclass
class CohereRerankConfig:
    """Resolved Cohere Rerank endpoint config."""

    endpoint: str
    api_key: str
    model: str
    # "bearer" | "api-key" — explicit when the project set it, else the Bearer default.
    auth: str = AUTH_BEARER
    # Whether the project explicitly picked an auth style (suppresses the api-key retry).
    auth_explicit: bool = False
    # Score Cohere's ordering into the labeling pool too, not just the by-stage metrics.
    pool_candidates: bool = False

    @property
    def url(self) -> str:
        """Full rerank URL. A configured endpoint that already names the route is used verbatim."""
        base = self.endpoint.rstrip("/")
        if base.endswith("/rerank"):
            return base
        return f"{base}/v2/rerank"


def _clean(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def get_cohere_rerank_config(
    project_settings: dict[str, Any] | None,
) -> CohereRerankConfig | None:
    """Resolve the Cohere Rerank config for a project, or None when it isn't configured.

    Per-project settings win over the deployment-wide env defaults, so one LoopLM instance can
    point different projects at different deployments. Returns None (both Cohere stages disabled)
    unless an endpoint *and* a key resolve — a half-configured reranker would fail per case, which
    is worse than not offering the stage.
    """
    s = project_settings or {}
    endpoint = _clean(s.get(ENDPOINT_KEY)) or _clean(settings.cohere_rerank_endpoint)
    api_key = _clean(s.get(KEY_KEY)) or _clean(settings.cohere_rerank_api_key)
    if not endpoint or not api_key:
        return None
    auth_raw = _clean(s.get(AUTH_KEY))
    auth = auth_raw.lower() if auth_raw and auth_raw.lower() in VALID_AUTH else AUTH_BEARER
    return CohereRerankConfig(
        endpoint=endpoint,
        api_key=api_key,
        model=_clean(s.get(MODEL_KEY)) or _clean(settings.cohere_rerank_model) or "rerank-v3.5",
        auth=auth,
        auth_explicit=auth_raw is not None and auth_raw.lower() in VALID_AUTH,
        pool_candidates=bool(s.get(POOL_KEY)),
    )


def _headers(api_key: str, auth: str) -> dict[str, str]:
    if auth == AUTH_API_KEY:
        return {"api-key": api_key, "Content-Type": "application/json"}
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _parse_results(payload: Any, doc_count: int) -> list[tuple[int, float]]:
    """``[(document index, relevance score)]`` from a rerank response.

    Accepts both the v2 shape (``{"results": [{"index": 0, "relevance_score": 0.9}]}``) and the
    v1 shape, which is identical for these two fields. Out-of-range indices are dropped rather
    than trusted, so a malformed response can't corrupt the pool.
    """
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise CohereRerankError(f"rerank response has no results array: {str(payload)[:200]}")
    out: list[tuple[int, float]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        score = item.get("relevance_score")
        if isinstance(idx, int) and 0 <= idx < doc_count and isinstance(score, (int, float)):
            out.append((idx, float(score)))
    return out


async def rerank_documents(
    client: httpx.AsyncClient,
    config: CohereRerankConfig,
    query: str,
    documents: Sequence[tuple[str, str]],
) -> dict[str, float]:
    """Cohere relevance scores (0..1) for ``documents`` against ``query``, keyed by chunk id.

    ``documents`` is ``[(chunk_id, text)]``; entries without usable text are dropped before the
    call (a cross-encoder has nothing to score without a body) and are simply absent from the
    result. Raises :class:`CohereRerankError` on a failed call so the caller can record the head
    as failed instead of silently reporting an empty stage.
    """
    pairs = [
        (cid, text.strip()[:_MAX_DOC_CHARS])
        for cid, text in documents
        if cid and isinstance(text, str) and text.strip()
    ]
    if not query.strip() or not pairs:
        return {}
    pairs = pairs[:_MAX_DOCS]

    body = {
        "model": config.model,
        "query": query.strip(),
        "documents": [text for _cid, text in pairs],
        "top_n": len(pairs),
    }
    auth_styles = (
        [config.auth]
        if config.auth_explicit
        # Unconfigured: Bearer (Cohere API + current Foundry deployments), then the api-key
        # header that older Azure serverless endpoints require.
        else [AUTH_BEARER, AUTH_API_KEY]
    )
    last_error: str | None = None
    for auth in auth_styles:
        try:
            response = await client.post(
                config.url, json=body, headers=_headers(config.api_key, auth), timeout=_TIMEOUT
            )
        except httpx.HTTPError as exc:
            raise CohereRerankError(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code in (401, 403) and auth != auth_styles[-1]:
            last_error = f"HTTP {response.status_code} with {auth} auth"
            continue
        if response.status_code >= 400:
            raise CohereRerankError(f"HTTP {response.status_code}: {response.text[:300]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise CohereRerankError(f"rerank response was not JSON: {response.text[:200]}") from exc
        scores = _parse_results(payload, len(pairs))
        return {pairs[idx][0]: score for idx, score in scores}
    raise CohereRerankError(last_error or "rerank authentication failed")


async def score_candidates(
    config: CohereRerankConfig,
    query: str,
    documents: Iterable[tuple[str, str]],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, float]:
    """:func:`rerank_documents` with an owned HTTP client when the caller has none."""
    docs = list(documents)
    if client is not None:
        return await rerank_documents(client, config, query, docs)
    async with httpx.AsyncClient() as owned:
        return await rerank_documents(owned, config, query, docs)


async def test_cohere_rerank(config: CohereRerankConfig) -> tuple[bool, str | None]:
    """Probe the configured endpoint with a trivial pair. Returns ``(ok, error)``, never raises."""
    try:
        scores = await score_candidates(
            config,
            "connection test",
            [("probe", "This is a connection test document for the reranker.")],
        )
    except CohereRerankError as exc:
        return False, str(exc)[:500]
    except Exception as exc:  # noqa: BLE001 — surface anything unexpected to the user as-is
        logger.warning("Cohere rerank probe failed: %s", exc)
        return False, f"{type(exc).__name__}: {exc}"[:500]
    return bool(scores), None if scores else "endpoint returned no scores"
