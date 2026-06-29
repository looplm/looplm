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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.index_providers.base import SEARCH_MODES, BaseIndexProvider

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


@dataclass
class PooledChunk:
    """One candidate in the labeling pool, with the heads that surfaced it."""

    chunk_id: str
    title: str | None = None
    url: str | None = None
    content_preview: str | None = None
    # Best-effort backend score (not comparable across heads — informational only).
    score: float | None = None
    # Subset of {"trace", "keyword", "vector", "hybrid"} — why this chunk is in the pool,
    # in the order the heads first surfaced it.
    provenance: list[str] = field(default_factory=list)
    # head -> 1-indexed rank this chunk held in that head's results (e.g. {"vector": 3,
    # "hybrid": 2}). Lets the labeler see *where* each method ranked the chunk, not just that
    # it surfaced it. A head missing from the map didn't surface this chunk.
    ranks: dict[str, int] = field(default_factory=dict)

    def _seen(self, head: str, rank: int) -> None:
        """Record that ``head`` surfaced this chunk at ``rank`` (keeping the best/first)."""
        if head not in self.provenance:
            self.provenance.append(head)
        # Heads don't repeat a chunk, but guard anyway: keep the strongest (lowest) rank.
        existing = self.ranks.get(head)
        if existing is None or rank < existing:
            self.ranks[head] = rank


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


async def assemble_pool(
    provider: BaseIndexProvider | None,
    query: str,
    *,
    trace_chunks: Iterable[dict[str, Any]] | None = None,
    modes: Iterable[str] = SEARCH_MODES,
    per_head_depth: int = DEFAULT_POOL_DEPTH,
    filters: dict[str, str] | None = None,
) -> PoolResult:
    """Build the deduped candidate pool for one query.

    Trace chunks (when given) seed the pool with provenance ``trace`` and rank first. Each
    requested mode then queries ``provider`` and merges its hits by ``chunk_id`` — a chunk
    already present gains the new mode's provenance; a new chunk is appended. A mode that the
    provider can't serve (``NotImplementedError``) or that errors is recorded in
    ``heads_failed`` and skipped, so a missing vector head never blocks the keyword pool.

    ``provider`` may be ``None`` (no index connected), in which case the pool is just the
    trace chunks — still useful, just not augmented.
    """
    pool: dict[str, PooledChunk] = {}
    heads_ran: list[str] = []
    heads_failed: dict[str, str] = {}

    if trace_chunks and _seed_from_trace(pool, trace_chunks):
        heads_ran.append("trace")

    if provider is not None and query.strip():
        for mode in modes:
            try:
                docs = await provider.search_documents(
                    query, per_head_depth, filters, mode=mode
                )
            except NotImplementedError as exc:
                heads_failed[mode] = str(exc) or "not supported by this index provider"
                continue
            except Exception as exc:  # vectorizer missing, transient backend error, etc.
                heads_failed[mode] = f"{type(exc).__name__}: {exc}"
                continue

            heads_ran.append(mode)
            for rank, d in enumerate(docs, start=1):
                if not d.id:
                    continue
                existing = pool.get(d.id)
                if existing is None:
                    chunk = PooledChunk(
                        chunk_id=d.id,
                        title=_coalesce(d.title),
                        url=_coalesce(d.url),
                        content_preview=_coalesce(d.snippet),
                        score=d.score,
                    )
                    chunk._seen(mode, rank)
                    pool[d.id] = chunk
                else:
                    existing._seen(mode, rank)
                    # Backfill anything the trace capture lacked.
                    existing.title = existing.title or _coalesce(d.title)
                    existing.url = existing.url or _coalesce(d.url)
                    existing.content_preview = existing.content_preview or _coalesce(d.snippet)
                    if existing.score is None:
                        existing.score = d.score

    return PoolResult(
        chunks=list(pool.values()), heads_ran=heads_ran, heads_failed=heads_failed
    )
