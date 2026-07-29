"""Assemble a TREC-style candidate pool for chunk labeling.

The chunks an eval run captured (``retrieved_chunks``) are only what the system *under test*
returned — so judging just those caps recall at "what we already found": a relevant chunk the
system never retrieved can never enter the pool and never gets credited. To make recall
honest, we pool additional candidates by querying the connected index several independent
ways (keyword/BM25, dense vector, hybrid/RRF) and merging them with the trace chunks, deduped
by chunk id.

This module is provider-agnostic: it takes any :class:`BaseIndexProvider` and the captured
trace chunks, runs the requested search heads, and returns a deduped pool where each chunk
carries the set of *provenances* that surfaced it (``trace``, ``keyword``, ``vector``,
``hybrid``). Heads a backend can't serve (e.g. vector search on an index with no embedding
field) are skipped and reported, not fatal.

Two kinds of head land in the pool: **positional** heads (a ranked result list, so the chunk's
rank in that list is the signal) and **score-ordered** rerank heads, which produce a relevance
score per chunk and no meaningful position — the reranker's own ordering *is* the score order.

The pool data model and the per-source merge rules live in :mod:`app.services.chunk_pool_merge`;
this module decides which heads run, in what order, and how their failures are reported.
"""

from __future__ import annotations

from typing import Any, Iterable

import httpx

from app.index_providers.base import SEARCH_MODES, BaseIndexProvider
from app.services.cohere_rerank import (
    AGENTIC_COHERE_STAGE,
    COHERE_RERANK_DEPTH,
    COHERE_STAGE,
    CohereRerankConfig,
    CohereRerankError,
    rerank_documents,
)
from app.services.chunk_pool_merge import (
    AgenticQuery,
    PoolResult,
    PooledChunk,
    _merge_agent_chunks,
    _merge_hit,
    _merge_rerank_hit,
    _seed_from_trace,
)

# Per-head retrieval depth for the broad set. Kept shallow (~10/head): the broad slice feeds
# aggregate metrics, so pooling deep there just multiplies judging effort for little signal.
# After dedup across heads this yields ~15-30 unique chunks/query — roughly 2-3x a typical
# reported cutoff (recall@5/@10), the TREC-style pooling target. Safety/adversarial pool
# deeper (see SLICE_POOL_DEPTH), where a relevant chunk missed at a low rank is the failure
# that matters.
DEFAULT_POOL_DEPTH = 10

# Deeper per-head depth for risk slices where a miss at deep rank is the failure that matters
# (safety/adversarial). Pools these to ~30-40 unique chunks. Slices not listed use the default.
SLICE_POOL_DEPTH = {"safety": 35, "adversarial": 35}

# Candidate depth for the agentic-rerank pass: each planned sub-query is re-run with the semantic
# (L2) reranker and the top results are scored. 50 matches Azure AI Search's semantic-ranker
# window (it reranks at most the top 50 L1 candidates of a query), so we ask for exactly that.
AGENTIC_RERANK_DEPTH = 50

# Heads whose ranking comes from a relevance score rather than a result position. They order by
# ``PooledChunk.rerank_scores[head]`` descending; every other head orders by ``ranks[head]``.
RERANK_HEADS = ("agentic_rerank", COHERE_STAGE, AGENTIC_COHERE_STAGE)


async def _cohere_base_pass(
    pool: dict[str, PooledChunk],
    provider: BaseIndexProvider,
    config: CohereRerankConfig,
    client: httpx.AsyncClient,
    query: str,
    depth: int,
    filters: dict[str, str] | None,
    query_vector: list[float] | None,
) -> bool:
    """Rescore the base question's hybrid top-``depth`` candidates with Cohere. True if it scored.

    Deliberately re-queries the hybrid head at the rerank window instead of reusing the shallow
    pool hybrid head: Azure's semantic head reranks the top 50 L1 candidates, so Cohere must see
    the same set for the two rerank stages to be comparable. Raises so the caller can report the
    head as failed (a silent empty stage reads as "Cohere is bad", which would be a lie).
    """
    docs = await provider.search_documents(
        query, depth, filters, mode="hybrid", query_vector=query_vector
    )
    by_id = {d.id: d for d in docs if d.id}
    scores = await rerank_documents(
        client, config, query, [(d.id, d.snippet or "") for d in by_id.values()]
    )
    for cid, score in scores.items():
        _merge_rerank_hit(pool, by_id[cid], head=COHERE_STAGE, score=score)
    return bool(scores)


async def _agentic_cohere_pass(
    pool: dict[str, PooledChunk],
    config: CohereRerankConfig,
    client: httpx.AsyncClient,
    query: str,
) -> bool:
    """Rescore the pooled agentic candidates against the ORIGINAL question. True if it scored.

    The agentic path merges its sub-queries positionally (first sub-query wins a tie), so a weak
    chunk from an early sub-query can outrank a later sub-query's best one. A single cross-encoder
    pass over the union against the user's actual question puts every candidate on one comparable
    scale, which is what a production "multi-query retrieve then rerank" step does. Only pooled
    chunks are scored (no new candidates enter here) and only those carrying text — a cross-encoder
    has nothing to judge without a body.
    """
    candidates = [
        (c.chunk_id, c.content_preview or "")
        for c in pool.values()
        if "agentic" in c.ranks and c.content_preview
    ]
    scores = await rerank_documents(client, config, query, candidates)
    for cid, score in scores.items():
        chunk = pool.get(cid)
        if chunk is not None:
            chunk._seen_rerank(AGENTIC_COHERE_STAGE, score)
    return bool(scores)


async def assemble_pool(
    provider: BaseIndexProvider | None,
    query: str,
    *,
    trace_chunks: Iterable[dict[str, Any]] | None = None,
    modes: Iterable[str] = SEARCH_MODES,
    per_head_depth: int = DEFAULT_POOL_DEPTH,
    filters: dict[str, str] | None = None,
    query_vector: list[float] | None = None,
    agentic_queries: Iterable[AgenticQuery] | None = None,
    agentic_rerank_depth: int | None = None,
    agent_chunks: Iterable[dict[str, Any]] | None = None,
    cohere: CohereRerankConfig | None = None,
    cohere_depth: int = COHERE_RERANK_DEPTH,
    http_client: httpx.AsyncClient | None = None,
) -> PoolResult:
    """Build the deduped candidate pool for one query.

    Trace chunks (when given) seed the pool with provenance ``trace`` and rank first. Each
    requested mode then queries ``provider`` and merges its hits by ``chunk_id`` — a chunk
    already present gains the new mode's provenance; a new chunk is appended. A mode that the
    provider can't serve (``NotImplementedError``) or that errors is recorded in
    ``heads_failed`` and skipped, so a missing vector head never blocks the keyword pool.

    When ``agentic_queries`` are given, each planned sub-query then runs the same modes and its
    hits are folded in with provenance ``agentic`` — raising the recall ceiling to what an
    agentic retriever would surface, not just the bare question. Their per-head failures are not
    re-reported (the base pass already did), and they never overwrite the base question's per-head
    ranks.

    When ``agentic_rerank_depth`` is also set, each sub-query is additionally re-run through the
    semantic (L2) reranker at that depth, and the best reranker score per chunk is recorded in
    ``rerank_scores["agentic_rerank"]`` (provenance ``agentic_rerank``). This models "agentic
    retrieve → rerank" without disturbing the positional-union ``agentic`` stage: reranked-only
    chunks get a score but no positional rank. Skipped silently when the index has no semantic
    configuration.

    When ``cohere`` is configured (see :mod:`app.services.cohere_rerank`), two cross-encoder heads
    also run: ``cohere_rerank`` rescores the base question's hybrid top-``cohere_depth`` (the same
    window Azure's semantic head reranks, so the two are comparable) and ``agentic_cohere``
    rescores the pooled agentic candidates against the original question. Both are score-ordered
    like ``agentic_rerank``; a failure is reported in ``heads_failed`` rather than raised.

    ``agent_chunks`` (the project's own retrieval agent's ranking, see
    :mod:`app.services.agent_retrieval`) are folded in last under provenance ``agent``, so the
    system being compared also contributes candidates to the pool it is judged against.

    ``provider`` may be ``None`` (no index connected), in which case the pool is just the
    trace chunks — still useful, just not augmented.
    """
    modes = list(modes)
    pool: dict[str, PooledChunk] = {}
    heads_ran: list[str] = []
    heads_failed: dict[str, str] = {}

    if trace_chunks and _seed_from_trace(pool, trace_chunks):
        heads_ran.append("trace")

    if provider is not None and query.strip():
        for mode in modes:
            try:
                docs = await provider.search_documents(
                    query, per_head_depth, filters, mode=mode, query_vector=query_vector
                )
            except NotImplementedError as exc:
                heads_failed[mode] = str(exc) or "not supported by this index provider"
                continue
            except Exception as exc:  # vectorizer missing, transient backend error, etc.
                heads_failed[mode] = f"{type(exc).__name__}: {exc}"
                continue

            heads_ran.append(mode)
            for rank, d in enumerate(docs, start=1):
                if d.id:
                    _merge_hit(pool, d, mode=mode, rank=rank, agentic_query=None)

    agentic_list = list(agentic_queries) if agentic_queries else []
    agentic_ran = False
    if provider is not None and agentic_list:
        for aq in agentic_list:
            if not aq.text.strip():
                continue
            for mode in modes:
                try:
                    docs = await provider.search_documents(
                        aq.text, per_head_depth, filters, mode=mode, query_vector=aq.vector
                    )
                except Exception:  # failures already surfaced by the base pass; skip quietly.
                    continue
                for rank, d in enumerate(docs, start=1):
                    if d.id:
                        agentic_ran = True
                        _merge_hit(pool, d, mode=None, rank=rank, agentic_query=aq.text)
    if agentic_ran:
        heads_ran.append("agentic")

    # Agentic-rerank: re-run each sub-query through the semantic reranker at a deeper window and
    # keep the best score per chunk. Ordered by score (not position) into the "agentic_rerank"
    # stage. Silent when the index has no semantic config (the semantic head raises).
    agentic_rerank_ran = False
    if provider is not None and agentic_list and agentic_rerank_depth:
        for aq in agentic_list:
            if not aq.text.strip():
                continue
            try:
                docs = await provider.search_documents(
                    aq.text, agentic_rerank_depth, filters, mode="semantic", query_vector=aq.vector
                )
            except Exception:  # no semantic config / transient error — skip this pass quietly.
                continue
            for d in docs:
                if d.id and isinstance(d.score, (int, float)):
                    agentic_rerank_ran = True
                    _merge_rerank_hit(pool, d, head="agentic_rerank", score=float(d.score))
    if agentic_rerank_ran:
        heads_ran.append("agentic_rerank")

    # Cross-encoder (Cohere) heads: one over the base question's hybrid window, one over the
    # agentic union. Both need the reranker configured; each reports its own failure so a bad key
    # or an unreachable endpoint is visible instead of looking like a reranker that found nothing.
    if provider is not None and cohere is not None:
        client = http_client or httpx.AsyncClient()
        try:
            if query.strip():
                try:
                    if await _cohere_base_pass(
                        pool, provider, cohere, client, query, cohere_depth, filters, query_vector
                    ):
                        heads_ran.append(COHERE_STAGE)
                except (CohereRerankError, NotImplementedError) as exc:
                    heads_failed[COHERE_STAGE] = str(exc) or type(exc).__name__
                except Exception as exc:  # noqa: BLE001 — transient index/network error
                    heads_failed[COHERE_STAGE] = f"{type(exc).__name__}: {exc}"
            if agentic_ran and query.strip():
                try:
                    if await _agentic_cohere_pass(pool, cohere, client, query):
                        heads_ran.append(AGENTIC_COHERE_STAGE)
                except CohereRerankError as exc:
                    heads_failed[AGENTIC_COHERE_STAGE] = str(exc)
                except Exception as exc:  # noqa: BLE001
                    heads_failed[AGENTIC_COHERE_STAGE] = f"{type(exc).__name__}: {exc}"
        finally:
            if http_client is None:
                await client.aclose()

    # Last, so index heads keep their ranks/metadata and the agent's own finds append after them.
    if agent_chunks is not None and _merge_agent_chunks(pool, agent_chunks):
        heads_ran.append("agent")

    return PoolResult(
        chunks=list(pool.values()), heads_ran=heads_ran, heads_failed=heads_failed
    )

