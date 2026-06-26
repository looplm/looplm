"""Tiny async Redis JSON cache.

Wraps a lazily-constructed ``redis.asyncio`` client with JSON get/set/delete helpers. Every
operation degrades gracefully: if Redis is unreachable the helpers behave as a cache miss
(get) or a no-op (set/delete) rather than raising, so caching is always a pure performance
optimization and never a hard dependency of a request.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level singleton. redis.asyncio clients are connection-pooled and safe to share across
# concurrent requests; construction is lazy (no socket is opened until the first command).
_client: aioredis.Redis | None = None


def _get_client() -> aioredis.Redis | None:
    global _client
    if _client is None:
        try:
            _client = aioredis.from_url(settings.redis_url, decode_responses=True)
        except Exception as exc:  # malformed URL, missing driver, etc.
            logger.warning("redis cache disabled: %s", exc)
            return None
    return _client


async def cache_get_json(key: str) -> Any | None:
    """Return the decoded JSON value at ``key``, or ``None`` on miss / any Redis error."""
    client = _get_client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except Exception as exc:  # connection refused, timeout, etc.
        logger.warning("redis get failed (%s): %s", key, exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def cache_set_json(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    """Store ``value`` as JSON at ``key`` with an optional TTL. Silent on any Redis error."""
    client = _get_client()
    if client is None:
        return
    try:
        data = json.dumps(value, separators=(",", ":"), default=str)
        await client.set(key, data, ex=ttl_seconds)
    except Exception as exc:
        logger.warning("redis set failed (%s): %s", key, exc)


async def cache_delete(key: str) -> None:
    """Delete ``key``. Silent on any Redis error."""
    client = _get_client()
    if client is None:
        return
    try:
        await client.delete(key)
    except Exception as exc:
        logger.warning("redis delete failed (%s): %s", key, exc)
