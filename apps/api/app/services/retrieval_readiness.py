"""Retrieval-readiness checks — is the project configured to *measure* retrieval quality?

Two config gaps silently produce empty per-stage metrics on the Retrieval/Labeling pages:

- No embedding model configured (or one that errors) → the dense/hybrid (RRF) heads can't run,
  so those stages come back blank rather than failing loudly.
- The connected index has no semantic configuration → the semantic (rerank) head raises, so the
  Reranked and Agentic+rerank stages are empty.

This module surfaces both as a readiness snapshot so the UI can warn instead of showing a blank
chart. The embedding probe is a live one-token embed (the same check as the owner-only
``test-embedding`` action), cached briefly in Redis so it isn't an API call on every page load.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache_get_json, cache_set_json
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.schemas.projects import EmbeddingTestResult
from app.schemas.retrieval import RetrievalReadiness
from app.services.analysis_llm import merge_llm_settings
from app.services.query_embedding import build_query_embedder

logger = logging.getLogger(__name__)

# The embed probe result is stable until settings change; cache it so a page-load banner doesn't
# hit the embedding API every time. Recompute is available via ``refresh``.
_READINESS_TTL = 300  # 5 minutes


async def probe_embedding_status(merged_settings: dict) -> EmbeddingTestResult:
    """Live one-token embed with the given settings — the shared 'does embedding work?' check.

    Returns ``configured=False`` when no embedding model is set, ``ok=True`` when the embed call
    succeeds (with the returned vector dimensions), or ``configured=True, ok=False`` with the
    provider error when it's set but the call fails (bad key/endpoint/deployment). Never raises.
    """
    embedder = build_query_embedder(merged_settings)
    if embedder is None:
        return EmbeddingTestResult(
            ok=False,
            configured=False,
            error="No embedding model configured. Set the embedding deployment/model in Settings.",
        )
    try:
        vector = await embedder.embed("connection test")
        return EmbeddingTestResult(
            ok=True, configured=True, model=embedder.model, dimensions=len(vector)
        )
    except Exception as exc:  # noqa: BLE001 — surface the provider error to the user
        logger.warning("Embedding readiness probe failed: %s", exc)
        return EmbeddingTestResult(ok=False, configured=True, model=embedder.model, error=str(exc)[:500])
    finally:
        await embedder.aclose()


async def compute_retrieval_readiness(
    db: AsyncSession, project: Project, *, refresh: bool = False
) -> RetrievalReadiness:
    """Readiness snapshot for the retrieval-metrics pages (embedding + index/semantic config).

    Uses the project's own settings (not personal ones) so it matches what the metrics computation
    actually runs on. The embedding probe is cached in Redis for a few minutes; ``refresh`` bypasses.
    """
    cache_key = f"embedding:readiness:{project.id}"
    embedding: EmbeddingTestResult | None = None
    if not refresh:
        cached = await cache_get_json(cache_key)
        if isinstance(cached, dict):
            embedding = EmbeddingTestResult(**cached)
    if embedding is None:
        embedding = await probe_embedding_status(merge_llm_settings(project.settings, None))
        await cache_set_json(cache_key, embedding.model_dump(), ttl_seconds=_READINESS_TTL)

    provider_row = (
        await db.execute(
            select(IndexProvider)
            .where(IndexProvider.project_id == project.id)
            .order_by(IndexProvider.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    index_connected = provider_row is not None
    semantic_configured = bool(
        provider_row is not None and (provider_row.config or {}).get("semantic_configuration")
    )

    return RetrievalReadiness(
        embedding=embedding,
        index_connected=index_connected,
        semantic_configured=semantic_configured,
    )
