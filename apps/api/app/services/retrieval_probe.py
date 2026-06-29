"""Live retrieval probe — what the system retrieves for a query, right now.

The chunk-level retrieval metrics need a "what did the system retrieve" signal to compare
against the human labels. Rather than depend on a stored eval run, we probe the connected
index live per query: run one search head and take its ranked chunk ids. Results are cached
in Redis per ``(project, test_id, mode, k)`` so the Pipeline page doesn't re-query the index
on every load.

The probe deliberately uses a single head (the project's "system" retrieval). LoopLM doesn't
store a production mode/top-k, so we prefer the richest head the index supports
(``hybrid`` → ``vector`` → ``keyword``) and retrieve to the largest reported cutoff.
"""

from __future__ import annotations

from uuid import UUID

from app.cache import cache_get_json, cache_set_json
from app.index_providers.base import BaseIndexProvider

# Preference order for the single "system" head, richest first. The first one the index can
# serve wins (others raise NotImplementedError / error and are skipped).
PROBE_MODES = ("hybrid", "vector", "keyword")

# Probe results are stable until the index is re-indexed; cache for the same window as the pool.
_PROBE_CACHE_TTL = 21_600  # 6 hours


def _probe_cache_key(project_id: UUID, test_id: str, k: int) -> str:
    return f"labeling:probe:{project_id}:{test_id}:{k}"


async def probe_retrieved_chunk_ids(
    provider: BaseIndexProvider, query: str, k: int
) -> tuple[list[str], str | None]:
    """Ranked chunk ids the system retrieves for ``query`` (top-k), plus the head used.

    Tries :data:`PROBE_MODES` in order and returns the first head that runs. Returns
    ``([], None)`` when the query is empty or no head is available.
    """
    if not query.strip():
        return [], None
    for mode in PROBE_MODES:
        try:
            docs = await provider.search_documents(query, k, None, mode=mode)
        except NotImplementedError:
            continue
        except Exception:  # vectorizer missing, transient backend error, etc.
            continue
        return [d.id for d in docs if d.id], mode
    return [], None


async def cached_probe_chunk_ids(
    provider: BaseIndexProvider,
    project_id: UUID,
    test_id: str,
    query: str,
    k: int,
    *,
    refresh: bool = False,
) -> list[str]:
    """``probe_retrieved_chunk_ids`` with a Redis cache keyed by (project, test_id, k)."""
    cache_key = _probe_cache_key(project_id, test_id, k)
    if not refresh:
        cached = await cache_get_json(cache_key)
        if cached is not None and isinstance(cached.get("chunk_ids"), list):
            return [c for c in cached["chunk_ids"] if isinstance(c, str)]
    chunk_ids, _mode = await probe_retrieved_chunk_ids(provider, query, k)
    await cache_set_json(cache_key, {"chunk_ids": chunk_ids}, ttl_seconds=_PROBE_CACHE_TTL)
    return chunk_ids
