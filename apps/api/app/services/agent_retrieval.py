"""Per-project custom-agent retrieval probe.

Scores a project's REAL retrieval agent as an extra by-stage retrieval stage, next to
the index-probe stages (sparse/dense/RRF/reranked/agentic). The agent is an external
HTTP endpoint that, given a query, returns a ranked chunk list WITHOUT generating an
answer — e.g. rde-gpt's ``POST /api/chat/retrieval``, which runs the exact prod
retrieval path (query expansion → mandatory search + drill-down → semantic rerank)
and returns ``rankedChunks`` at chunk granularity.

Unlike the other stages (LoopLM re-querying the connected index itself), this stage
measures what the customer's own agent actually retrieves. Config lives in
``project.settings`` (see the ``*_KEY`` constants); the token is masked on read by
``routers/projects.py``. Probes are Redis-cached and degraded (``keyword-fallback``)
runs are dropped so an infra artifact never folds into the metrics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.cache import cache_get_json, cache_set_json
from app.services.eval_executor_helpers import _retrieval_mode_from_parsed, _safe_json_loads
from app.services.eval_runners import _call_target_api
from app.services.model_resilience import DEGRADED_RETRIEVAL_MODE
from app.services.retrieval_config import extract_retrieved_chunks

logger = logging.getLogger(__name__)

# Pool head + default display label for the agent stage. The label is overridable per
# project (``agent_retrieval_label``) so it can read e.g. "RDE-GPT agent".
AGENT_STAGE = "agent"
DEFAULT_AGENT_LABEL = "Custom agent"

# ``project.settings`` keys for the agent-retrieval config.
ENDPOINT_KEY = "agent_retrieval_endpoint"
TOKEN_KEY = "agent_retrieval_token"
LABEL_KEY = "agent_retrieval_label"
TEMPLATE_KEY = "agent_retrieval_request_template"
POOL_KEY = "agent_retrieval_pool"

# The shared-secret header rde-gpt's retrieval endpoint expects (EVAL_PROBE_TOKEN).
TOKEN_HEADER = "X-Eval-Token"
_DEFAULT_REQUEST_TEMPLATE = {"messages": [{"role": "user", "content": "{prompt}"}]}
# Agent rankings are stable until the index/agent changes; cache for the same window as
# the index probe so the Retrieval page doesn't re-hit the agent on every compute.
_AGENT_CACHE_TTL = 21_600  # 6 hours

# Depth every caller probes at, so the by-stage metrics run and the labeling pool share ONE
# cached ranking per case (the cache key carries the depth). 50 is the deepest reported cutoff;
# shallower consumers (the labeling pool, which pools ~10/head) slice this list.
AGENT_PROBE_DEPTH = 50

# Keep the cached ranking small: the labeling UI shows a preview and fetches full text on demand.
_PREVIEW_CHARS = 1200


@dataclass
class AgentRetrievalConfig:
    """Resolved agent-retrieval endpoint config for a project."""

    endpoint: str
    token: str | None
    label: str
    request_template: dict
    # Fold the agent's top chunks into the labeling pool as their own head, so its candidates
    # get judged instead of counting as misses (see :mod:`app.services.labeling_pool`).
    pool_candidates: bool = False


def get_agent_retrieval_config(settings: dict[str, Any] | None) -> AgentRetrievalConfig | None:
    """Resolve the agent-retrieval config from a project's settings, or None when unset.

    Returns None (agent stage disabled) unless a non-blank endpoint is configured.
    """
    s = settings or {}
    endpoint = s.get(ENDPOINT_KEY)
    if not isinstance(endpoint, str) or not endpoint.strip():
        return None
    token = s.get(TOKEN_KEY)
    label = s.get(LABEL_KEY)
    template = s.get(TEMPLATE_KEY)
    return AgentRetrievalConfig(
        endpoint=endpoint.strip(),
        token=token.strip() if isinstance(token, str) and token.strip() else None,
        label=label.strip() if isinstance(label, str) and label.strip() else DEFAULT_AGENT_LABEL,
        request_template=template if isinstance(template, dict) and template else dict(_DEFAULT_REQUEST_TEMPLATE),
        pool_candidates=bool(s.get(POOL_KEY)),
    )


def _agent_cache_key(project_id: UUID, test_id: str, n: int) -> str:
    return f"labeling:agentprobe:{project_id}:{test_id}:{n}"


def _slim_chunk(c: dict[str, Any]) -> dict[str, Any]:
    """The subset of a retrieved chunk worth caching: identity + what the labeler needs to read."""
    preview = c.get("content_preview")
    return {
        "chunk_id": c["chunk_id"],
        "title": c.get("title"),
        "url": c.get("url"),
        "content_preview": preview[:_PREVIEW_CHARS] if isinstance(preview, str) else None,
        "score": c.get("score") if isinstance(c.get("score"), (int, float)) else None,
    }


def _cached_chunks(cached: Any) -> list[dict[str, Any]] | None:
    """Full chunk records from a cache entry, or None when it holds only the legacy id list."""
    if not isinstance(cached, dict) or not isinstance(cached.get("chunks"), list):
        return None
    return [c for c in cached["chunks"] if isinstance(c, dict) and isinstance(c.get("chunk_id"), str)]


@dataclass
class AgentProbeResult:
    """One probe's outcome, separating "the agent ranked nothing" from "we couldn't ask it".

    Both used to surface as an empty list, which the metrics then scored as a total miss. That
    is right for a genuine empty ranking and wrong for an unreachable endpoint, a 500 or a
    degraded keyword-fallback run: those are measurement failures and must leave the average
    rather than drag it down. ``failure`` carries the reason for the UI when set.
    """

    chunks: list[dict[str, Any]]
    failure: str | None = None


async def probe_agent_chunk_ids(
    client: httpx.AsyncClient,
    config: AgentRetrievalConfig,
    project_id: UUID,
    test_id: str,
    query: str,
    n: int,
    *,
    refresh: bool = False,
) -> list[str] | None:
    """Ranked chunk ids the customer's agent retrieves for ``query`` (top-n), Redis-cached.

    Thin projection of :func:`probe_agent_chunks` for the metrics path, which scores positions
    and needs nothing else. Reads id-only cache entries written before the pooling head existed.

    Returns ``None`` when the agent could not be measured for this case (unreachable endpoint,
    HTTP error, degraded keyword-fallback run, or an empty query) so the caller can exclude it
    instead of recording a miss. An empty list means the agent genuinely ranked nothing.
    """
    if not refresh:
        cached = await cache_get_json(_agent_cache_key(project_id, test_id, n))
        chunks = _cached_chunks(cached)
        if chunks is not None:
            return [c["chunk_id"] for c in chunks]
        if isinstance(cached, dict) and isinstance(cached.get("chunk_ids"), list):
            return [c for c in cached["chunk_ids"] if isinstance(c, str)]
    result = await _probe_agent(client, config, project_id, test_id, query, n, refresh=refresh)
    if result.failure is not None:
        return None
    return [c["chunk_id"] for c in result.chunks]


async def probe_agent_chunks(
    client: httpx.AsyncClient,
    config: AgentRetrievalConfig,
    project_id: UUID,
    test_id: str,
    query: str,
    n: int,
    *,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """Ranked chunks the customer's agent retrieves for ``query`` (top-n), Redis-cached.

    Each record carries the chunk id plus the title/url/preview the labeling pool needs to
    render a judgeable candidate, in the agent's own ranking order.

    Returns ``[]`` (the agent contributes nothing for this case) when the query is empty, the
    endpoint is unreachable/errors, or the run degraded to keyword-only retrieval. Callers that
    must tell those apart — the metrics, which would otherwise score a 500 as a miss — use
    :func:`probe_agent_chunk_ids` or :func:`_probe_agent` instead.
    """
    return (
        await _probe_agent(client, config, project_id, test_id, query, n, refresh=refresh)
    ).chunks


async def _probe_agent(
    client: httpx.AsyncClient,
    config: AgentRetrievalConfig,
    project_id: UUID,
    test_id: str,
    query: str,
    n: int,
    *,
    refresh: bool = False,
) -> AgentProbeResult:
    """Probe the agent once, reporting whether it answered at all (see :class:`AgentProbeResult`).

    A hard failure is logged, not cached, so a transient outage doesn't stick for the whole TTL.
    """
    if not query.strip():
        return AgentProbeResult([], failure="empty query")
    cache_key = _agent_cache_key(project_id, test_id, n)
    if not refresh:
        chunks = _cached_chunks(await cache_get_json(cache_key))
        if chunks is not None:
            return AgentProbeResult(chunks)

    headers = {TOKEN_HEADER: config.token} if config.token else {}
    try:
        # response_path is unused (we parse rankedChunks from the raw JSON); pass a harmless
        # default. No filters — probe the whole index, matching the index-probe stages.
        _answer, raw_response, _elapsed = await _call_target_api(
            client,
            config.endpoint,
            config.request_template,
            "answer",
            headers,
            query,
            team_filter=[],
            tag_filter=[],
            filter_enabled=False,
        )
    except Exception as exc:  # noqa: BLE001 — unreachable/4xx/5xx: agent stage skips this case
        logger.warning("Agent retrieval probe failed for test %s: %s", test_id, exc)
        return AgentProbeResult([], failure=f"{type(exc).__name__}: {exc}"[:200])

    parsed = _safe_json_loads(raw_response)
    # A keyword-fallback run means the agent's vector path failed for every query (its
    # reranker never ran) — not representative of prod, so don't fold it into the metrics.
    if _retrieval_mode_from_parsed(parsed) == DEGRADED_RETRIEVAL_MODE:
        logger.info("Agent retrieval probe degraded (keyword-fallback) for test %s; skipped", test_id)
        return AgentProbeResult([], failure="degraded keyword-fallback run")

    extracted = extract_retrieved_chunks(parsed)  # reads rankedChunks (chunk-level) first
    chunks = [_slim_chunk(c) for c in extracted if c.get("chunk_id")][:n]
    await cache_set_json(cache_key, {"chunks": chunks}, ttl_seconds=_AGENT_CACHE_TTL)
    return AgentProbeResult(chunks)
