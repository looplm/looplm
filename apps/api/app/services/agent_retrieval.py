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

# The shared-secret header rde-gpt's retrieval endpoint expects (EVAL_PROBE_TOKEN).
TOKEN_HEADER = "X-Eval-Token"
_DEFAULT_REQUEST_TEMPLATE = {"messages": [{"role": "user", "content": "{prompt}"}]}
# Agent rankings are stable until the index/agent changes; cache for the same window as
# the index probe so the Retrieval page doesn't re-hit the agent on every compute.
_AGENT_CACHE_TTL = 21_600  # 6 hours


@dataclass
class AgentRetrievalConfig:
    """Resolved agent-retrieval endpoint config for a project."""

    endpoint: str
    token: str | None
    label: str
    request_template: dict


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
    )


def _agent_cache_key(project_id: UUID, test_id: str, n: int) -> str:
    return f"labeling:agentprobe:{project_id}:{test_id}:{n}"


async def probe_agent_chunk_ids(
    client: httpx.AsyncClient,
    config: AgentRetrievalConfig,
    project_id: UUID,
    test_id: str,
    query: str,
    n: int,
    *,
    refresh: bool = False,
) -> list[str]:
    """Ranked chunk ids the customer's agent retrieves for ``query`` (top-n), Redis-cached.

    Returns ``[]`` (agent stage contributes nothing for this case) when the query is empty,
    the endpoint is unreachable/errors, or the run degraded to keyword-only retrieval — none
    of which should be scored as the agent's real ranking. A hard failure is logged, not
    cached, so a transient outage doesn't stick for the whole TTL.
    """
    if not query.strip():
        return []
    cache_key = _agent_cache_key(project_id, test_id, n)
    if not refresh:
        cached = await cache_get_json(cache_key)
        if cached is not None and isinstance(cached.get("chunk_ids"), list):
            return [c for c in cached["chunk_ids"] if isinstance(c, str)]

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
        return []

    parsed = _safe_json_loads(raw_response)
    # A keyword-fallback run means the agent's vector path failed for every query (its
    # reranker never ran) — not representative of prod, so don't fold it into the metrics.
    if _retrieval_mode_from_parsed(parsed) == DEGRADED_RETRIEVAL_MODE:
        logger.info("Agent retrieval probe degraded (keyword-fallback) for test %s; skipped", test_id)
        return []

    chunks = extract_retrieved_chunks(parsed)  # reads rankedChunks (chunk-level) first
    chunk_ids = [c["chunk_id"] for c in chunks if c.get("chunk_id")][:n]
    await cache_set_json(cache_key, {"chunk_ids": chunk_ids}, ttl_seconds=_AGENT_CACHE_TTL)
    return chunk_ids
