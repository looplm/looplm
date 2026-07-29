"""Pool data model + merge primitives for the chunk-labeling candidate pool.

The pool is a ``{chunk_id: PooledChunk}`` map that several independent retrieval heads merge
into: each head contributes its hits, and a chunk already present just gains that head's
provenance (plus its rank or rerank score) instead of being duplicated. This module owns that
data model and the per-source merge functions; :mod:`app.services.chunk_pool` owns the
orchestration that decides which heads run and in what order.

Split out so the merge rules — which head may write a rank, which may only write a score, and
which fields backfill from a later source — stay readable in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class AgenticQuery:
    """A planner-produced sub-query plus its embedding (``None`` → provider text fallback).

    The agentic path (see :mod:`app.services.query_planner`) decomposes a case's question into
    several focused sub-queries; each carries its own embedding so the vector/hybrid heads can run
    on it even when the index has no server-side vectorizer.
    """

    text: str
    vector: list[float] | None = None


@dataclass
class PooledChunk:
    """One candidate in the labeling pool, with the heads that surfaced it."""

    chunk_id: str
    title: str | None = None
    url: str | None = None
    content_preview: str | None = None
    # Best-effort backend score (not comparable across heads — informational only).
    score: float | None = None
    # Subset of {"trace", "keyword", "vector", "hybrid", "agentic", "agent"} — why this chunk is
    # in the pool, in the order the heads first surfaced it. "agentic" means an LLM-planned
    # sub-query found it (in addition to whichever index heads, if any, ran on the base
    # question); "agent" means the project's own retrieval agent returned it.
    provenance: list[str] = field(default_factory=list)
    # head -> 1-indexed rank this chunk held in that head's results (e.g. {"vector": 3,
    # "hybrid": 2}). Lets the labeler see *where* each method ranked the chunk, not just that
    # it surfaced it. A head missing from the map didn't surface this chunk. The pseudo-head
    # "agentic" holds the best rank any planned sub-query gave the chunk.
    ranks: dict[str, int] = field(default_factory=dict)
    # The agentic sub-queries that surfaced this chunk, in the order they first did. Empty unless
    # agentic pooling ran. Drives the per-chunk "found by query X" display.
    agentic_queries: list[str] = field(default_factory=list)
    # rerank head -> best relevance score from it (see ``chunk_pool.RERANK_HEADS``).
    # ``agentic_rerank`` is Azure's semantic rerankerScore (0-4); the Cohere heads are 0-1. These
    # order their stage on score alone, as opposed to the positional-rank union of the other heads.
    # A head missing from the map wasn't run, or didn't score this chunk.
    rerank_scores: dict[str, float] = field(default_factory=dict)

    def _seen(self, head: str, rank: int) -> None:
        """Record that ``head`` surfaced this chunk at ``rank`` (keeping the best/first)."""
        if head not in self.provenance:
            self.provenance.append(head)
        # Heads don't repeat a chunk, but guard anyway: keep the strongest (lowest) rank.
        existing = self.ranks.get(head)
        if existing is None or rank < existing:
            self.ranks[head] = rank

    def _seen_agentic(self, query: str, rank: int) -> None:
        """Record that an agentic sub-query surfaced this chunk at ``rank``.

        Agentic hits don't write into the per-head ranks (those stay authoritative for the base
        question's badges); they land under the "agentic" pseudo-head, keeping the best rank.
        """
        if "agentic" not in self.provenance:
            self.provenance.append("agentic")
        existing = self.ranks.get("agentic")
        if existing is None or rank < existing:
            self.ranks["agentic"] = rank
        if query and query not in self.agentic_queries:
            self.agentic_queries.append(query)

    def _seen_rerank(self, head: str, score: float) -> None:
        """Record a rerank score for ``head`` (keeping the best).

        This is a relevance score, not a rank position, so it doesn't touch ``ranks``; it lands in
        ``rerank_scores[head]`` and orders that head's stage on its own.
        """
        if head not in self.provenance:
            self.provenance.append(head)
        existing = self.rerank_scores.get(head)
        if existing is None or score > existing:
            self.rerank_scores[head] = score


@dataclass
class PoolResult:
    """The assembled pool plus which heads contributed or failed."""

    chunks: list[PooledChunk]
    heads_ran: list[str] = field(default_factory=list)
    # head -> reason it produced nothing (capability gap, vectorizer missing, error).
    heads_failed: dict[str, str] = field(default_factory=dict)


def _coalesce(*values: Any) -> str | None:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v
    return None


def _seed_from_trace(
    pool: dict[str, PooledChunk], trace_chunks: Iterable[dict[str, Any]]
) -> bool:
    """Seed the pool with the trace-captured chunks; returns True if any were added.

    Trace chunks arrive in the order the system under test ranked them, so their position is
    the ``trace`` head's rank.
    """
    seeded = False
    rank = 0
    for c in trace_chunks:
        if not isinstance(c, dict):
            continue
        chunk_id = c.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id:
            continue
        seeded = True
        rank += 1
        existing = pool.get(chunk_id)
        if existing is None:
            score = c.get("score")
            chunk = PooledChunk(
                chunk_id=chunk_id,
                title=_coalesce(c.get("title")),
                url=_coalesce(c.get("url")),
                content_preview=_coalesce(c.get("content_preview"), c.get("content")),
                score=float(score) if isinstance(score, (int, float)) else None,
            )
            chunk._seen("trace", rank)
            pool[chunk_id] = chunk
        else:
            existing._seen("trace", rank)
    return seeded


def _merge_agent_chunks(
    pool: dict[str, PooledChunk], agent_chunks: Iterable[dict[str, Any]]
) -> bool:
    """Fold the project's own retrieval agent's ranking into the pool; True if any were added.

    Without this the agent is judged on a pool it never contributed to: chunks only it returns
    stay unjudged and score as misses (TREC pool bias). Its list arrives in the agent's final
    ranking order, so position is the ``agent`` head's rank.
    """
    merged = False
    rank = 0
    for c in agent_chunks:
        if not isinstance(c, dict):
            continue
        chunk_id = c.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id:
            continue
        merged = True
        rank += 1
        score = c.get("score")
        existing = pool.get(chunk_id)
        if existing is None:
            existing = PooledChunk(chunk_id=chunk_id)
            pool[chunk_id] = existing
        existing._seen("agent", rank)
        # Backfill display fields: index heads win when they already resolved them.
        existing.title = existing.title or _coalesce(c.get("title"))
        existing.url = existing.url or _coalesce(c.get("url"))
        existing.content_preview = existing.content_preview or _coalesce(
            c.get("content_preview"), c.get("content")
        )
        if existing.score is None and isinstance(score, (int, float)):
            existing.score = float(score)
    return merged


def _merge_hit(
    pool: dict[str, PooledChunk], d: Any, *, mode: str | None, rank: int, agentic_query: str | None
) -> None:
    """Merge one index hit into the pool, recording its head/agentic provenance + rank.

    ``mode`` records a base-question head (keyword/vector/hybrid); ``agentic_query`` records the
    planned sub-query that surfaced it. Exactly one is set per call.
    """
    existing = pool.get(d.id)
    if existing is None:
        chunk = PooledChunk(
            chunk_id=d.id,
            title=_coalesce(d.title),
            url=_coalesce(d.url),
            content_preview=_coalesce(d.snippet),
            score=d.score,
        )
        if agentic_query is not None:
            chunk._seen_agentic(agentic_query, rank)
        else:
            chunk._seen(mode, rank)
        pool[d.id] = chunk
        return
    if agentic_query is not None:
        existing._seen_agentic(agentic_query, rank)
    else:
        existing._seen(mode, rank)
    # Backfill anything an earlier (e.g. trace) capture lacked.
    existing.title = existing.title or _coalesce(d.title)
    existing.url = existing.url or _coalesce(d.url)
    existing.content_preview = existing.content_preview or _coalesce(d.snippet)
    if existing.score is None:
        existing.score = d.score


def _merge_rerank_hit(pool: dict[str, PooledChunk], d: Any, *, head: str, score: float) -> None:
    """Fold one rerank hit into the pool, recording its relevance score under ``head``.

    Unlike :func:`_merge_hit`, this never assigns a positional rank — the reranked list is ordered
    by score, and it must not inflate the positional-union "agentic" stage. A chunk the rerank pass
    surfaces that no other head found still enters the pool (a legitimate reranked candidate).
    """
    existing = pool.get(d.id)
    if existing is None:
        chunk = PooledChunk(
            chunk_id=d.id,
            title=_coalesce(d.title),
            url=_coalesce(d.url),
            content_preview=_coalesce(d.snippet),
            score=d.score,
        )
        chunk._seen_rerank(head, score)
        pool[d.id] = chunk
        return
    existing._seen_rerank(head, score)
    existing.title = existing.title or _coalesce(d.title)
    existing.url = existing.url or _coalesce(d.url)
    existing.content_preview = existing.content_preview or _coalesce(d.snippet)
    if existing.score is None:
        existing.score = d.score
