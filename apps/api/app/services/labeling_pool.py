"""Per-case labeling-pool assembly: which candidate chunks get judged.

Sits between the raw pooling primitives (:mod:`app.services.chunk_pool`) and every consumer
that must judge the *same* chunks: the labeling view, the AI judge, the judge preview, the
diagnosis endpoint and the by-stage retrieval metrics. Resolves the case's per-head depth,
runs the connected index's heads (plus the planned agentic sub-queries and, when the project
opts in, its own retrieval agent), and caches the assembled pool in Redis.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache_get_json, cache_set_json
from app.index_providers.registry import build_index_provider
from app.models.chunk_labels import TestCaseLabelingStatus
from app.models.index_providers import IndexProvider
from app.models.project import Project
from app.services.agent_retrieval import (
    AGENT_PROBE_DEPTH,
    AgentRetrievalConfig,
    get_agent_retrieval_config,
    probe_agent_chunks,
)
from app.services.analysis_llm import merge_llm_settings
from app.services.index_fields import (
    INDEX_HEADING_FIELDS,
    INDEX_TEXT_FIELDS,
    first_str_field,
)
from app.services.chunk_pool import (
    DEFAULT_POOL_DEPTH,
    SLICE_POOL_DEPTH,
    AgenticQuery,
    PooledChunk,
    PoolResult,
    assemble_pool,
)
from app.services.query_embedding import embed_query

logger = logging.getLogger(__name__)

# Hard cap on per-head pool depth so a "load deeper pool" request can't hammer the index.
_MAX_POOL_DEPTH = 50

# The auto-pool (a case's own input against the index heads) is user-independent and stable
# until the index is re-indexed, so we cache the assembled pool in Redis. This is what lets the
# labeling view eager-load per-method ranks for every case without re-hitting Azure on every
# page open — mirroring the reference design, which persists the pool on first visit. Manual
# searches (an explicit ``q``) always run fresh and are never cached. TTL is a freshness bound;
# changing a case's slice changes its depth, which changes the key, so it re-pools immediately.
_POOL_CACHE_TTL = 21_600  # 6 hours

# Cap on a hydrated preview: the row shows an excerpt and fetches the full body on demand.
_PREVIEW_CHARS = 1200


def _agentic_signature(queries: list[str]) -> str:
    """Stable short signature of the agentic query set, for the pool cache key.

    Folding agentic queries changes the pool, so the cache must distinguish a base-only pool
    ("0") from one built with a given set of sub-queries. Re-planning yields a different set →
    a different key → a natural cache miss, so no explicit invalidation is needed.
    """
    if not queries:
        return "0"
    joined = "\n".join(sorted(queries))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def _pool_cache_key(
    project_id: UUID,
    test_id: str,
    per_head: int,
    agentic_sig: str,
    rerank_depth: int | None = None,
    with_agent: bool = False,
) -> str:
    base = f"labeling:pool:{project_id}:{test_id}:{per_head}:{agentic_sig}"
    # A rerank pool carries extra scored candidates, so it must not collide with the labeling pool
    # (which never sets rerank_depth); only the rerank variant gets the ``:r{depth}`` suffix.
    if rerank_depth:
        base = f"{base}:r{rerank_depth}"
    # Same reason for the agent head: turning it on adds candidates, so the two pools are
    # different sets and must not share a key. Off → the key is byte-identical to before.
    return f"{base}:a" if with_agent else base


def _serialize_pool(pool: PoolResult, computed_at: str) -> dict:
    return {
        "computed_at": computed_at,
        "heads_ran": pool.heads_ran,
        "heads_failed": pool.heads_failed,
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "title": c.title,
                "url": c.url,
                "content_preview": c.content_preview,
                "score": c.score,
                "provenance": c.provenance,
                "ranks": c.ranks,
                "agentic_queries": c.agentic_queries,
                "agentic_rerank_score": c.agentic_rerank_score,
            }
            for c in pool.chunks
        ],
    }


def _deserialize_pool(data: dict) -> PoolResult:
    return PoolResult(
        chunks=[
            PooledChunk(
                chunk_id=c["chunk_id"],
                title=c.get("title"),
                url=c.get("url"),
                content_preview=c.get("content_preview"),
                score=c.get("score"),
                provenance=list(c.get("provenance") or []),
                ranks={k: int(v) for k, v in (c.get("ranks") or {}).items()},
                agentic_queries=list(c.get("agentic_queries") or []),
                agentic_rerank_score=c.get("agentic_rerank_score"),
            )
            for c in data.get("chunks", [])
        ],
        heads_ran=list(data.get("heads_ran") or []),
        heads_failed=dict(data.get("heads_failed") or {}),
    )


async def _case_pool_depth(
    db: AsyncSession, project: Project, test_id: str, depth: int | None
) -> int:
    """Per-head pool depth for a case: explicit ``depth`` wins, else the case's slice depth."""
    if depth:
        return max(1, min(depth, _MAX_POOL_DEPTH))
    slice_value = (
        await db.execute(
            select(TestCaseLabelingStatus.slice).where(
                TestCaseLabelingStatus.project_id == project.id,
                TestCaseLabelingStatus.test_id == test_id,
            )
        )
    ).scalar_one_or_none()
    return SLICE_POOL_DEPTH.get(slice_value or "", DEFAULT_POOL_DEPTH)


async def _agent_pool_chunks(
    config: AgentRetrievalConfig,
    project_id: UUID,
    test_id: str,
    query: str,
    depth: int,
    *,
    refresh: bool,
) -> list[dict]:
    """The agent's own top-``depth`` chunks for this case.

    Probed at :data:`AGENT_PROBE_DEPTH` (not ``depth``) so this shares the one cached ranking
    per case with the by-stage metrics run, then sliced to the same depth the index heads
    contribute — pooling stays symmetric across systems, which is the point of pooling.
    """
    async with httpx.AsyncClient() as client:
        chunks = await probe_agent_chunks(
            client, config, project_id, test_id, query, AGENT_PROBE_DEPTH, refresh=refresh
        )
    return chunks[:depth]


async def _hydrate_from_index(provider, chunks: list[PooledChunk]) -> None:
    """Fill missing title/preview on pooled chunks by reading them from the index.

    Agent responses often carry ids and little else (rde-gpt's ``rankedChunks`` has no body), so
    a chunk only the agent found would render as a blank row. The index heads' own hits already
    arrive with a snippet, so this only touches what's missing.
    """
    ids = [c.chunk_id for c in chunks if not c.content_preview or not c.title]
    if not ids or provider is None:
        return
    try:
        docs = await provider.fetch_documents_by_key(ids)
    except Exception:  # noqa: BLE001 — capability gap / transient error: leave the row sparse
        logger.exception("Hydrating %d pooled chunks from the index failed", len(ids))
        return
    by_id = {c.chunk_id: c for c in chunks}
    for cid, fields in docs.items():
        chunk = by_id.get(cid)
        if chunk is None or not isinstance(fields, dict):
            continue
        text = first_str_field(fields, INDEX_TEXT_FIELDS)
        chunk.content_preview = chunk.content_preview or (text[:_PREVIEW_CHARS] if text else None)
        chunk.title = chunk.title or first_str_field(fields, INDEX_HEADING_FIELDS)


async def assemble_case_pool(
    db: AsyncSession,
    project: Project,
    test_id: str,
    query: str,
    *,
    depth: int | None = None,
    manual: bool = False,
    refresh: bool = False,
    agentic_queries: list[str] | None = None,
    rerank_depth: int | None = None,
) -> tuple[PoolResult, str | None, bool]:
    """Assemble (or load from cache) the candidate pool for a case's query.

    Shared by the labeling-pool view and the AI judge so both judge the *same* chunks. Resolves
    the per-head depth from the case's slice, runs the connected index's heads via
    :func:`assemble_pool`, and caches the auto-pool in Redis (a manual ``q`` is always fresh and
    never cached; ``refresh`` bypasses the cache). When ``agentic_queries`` are given, each is
    embedded and folded into the pool, and the cache key carries their signature so a base-only
    pool and an agentic pool never collide. When ``rerank_depth`` is set, the agentic sub-queries
    are also scored through the semantic reranker at that depth (a separate cache entry, so the
    labeling pool is untouched). When the project opts into agent pooling, the configured
    retrieval agent contributes its own top chunks as the ``agent`` head — an unreachable agent
    is reported in ``heads_failed`` rather than failing the pool. Returns
    ``(pool, computed_at, provider_connected)``.
    """
    per_head = await _case_pool_depth(db, project, test_id, depth)
    agentic_queries = [q for q in (agentic_queries or []) if q and q.strip()]
    agent_config = get_agent_retrieval_config(project.settings)
    if agent_config is not None and not agent_config.pool_candidates:
        agent_config = None

    provider_row = (
        await db.execute(
            select(IndexProvider)
            .where(IndexProvider.project_id == project.id)
            .order_by(IndexProvider.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    cache_key = (
        None
        if manual
        else _pool_cache_key(
            project.id,
            test_id,
            per_head,
            _agentic_signature(agentic_queries),
            rerank_depth,
            with_agent=agent_config is not None,
        )
    )
    if cache_key and not refresh:
        cached = await cache_get_json(cache_key)
        if cached is not None:
            return _deserialize_pool(cached), cached.get("computed_at"), provider_row is not None

    # Embed each query ourselves so vector/hybrid heads work even when the index has no
    # server-side vectorizer. None (unconfigured or failed) → text-based vector search fallback.
    llm_settings = merge_llm_settings(project.settings, None)
    query_vector = await embed_query(llm_settings, query)
    agentic_specs = [
        AgenticQuery(text=q, vector=await embed_query(llm_settings, q)) for q in agentic_queries
    ]

    agent_chunks: list[dict] | None = None
    agent_error: str | None = None
    if agent_config is not None:
        try:
            agent_chunks = await _agent_pool_chunks(
                agent_config, project.id, test_id, query, per_head, refresh=refresh
            )
        except Exception as exc:  # noqa: BLE001 — the customer's endpoint must never break labeling
            logger.warning("Agent pooling failed for test %s: %s", test_id, exc)
            agent_error = f"{type(exc).__name__}: {exc}"
        if not agent_chunks and agent_error is None:
            # The probe swallows unreachable/degraded runs and returns nothing; say so instead of
            # silently pooling a smaller set than the labeler was promised.
            agent_error = "agent returned no ranking for this query"

    provider = build_index_provider(provider_row) if provider_row is not None else None
    try:
        pool = await assemble_pool(
            provider,
            query,
            per_head_depth=per_head,
            query_vector=query_vector,
            agentic_queries=agentic_specs or None,
            agentic_rerank_depth=rerank_depth,
            agent_chunks=agent_chunks,
        )
        if agent_chunks:
            await _hydrate_from_index(provider, pool.chunks)
    finally:
        if provider is not None:
            await provider.aclose()
    if agent_error:
        pool.heads_failed["agent"] = agent_error
    computed_at = datetime.now(timezone.utc).isoformat()
    if cache_key:
        await cache_set_json(
            cache_key, _serialize_pool(pool, computed_at), ttl_seconds=_POOL_CACHE_TTL
        )
    return pool, computed_at, provider_row is not None
