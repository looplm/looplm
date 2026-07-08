"""Redis result cache for the labels-based retrieval-quality metrics.

The overall and by-stage metrics are only computed when the user presses Compute (or Recompute),
so the full computed response is cached keyed by the exact settings, stamped with the time it was
computed. Re-opening the page then serves instantly and the UI can show when the numbers are from.

Keyed by ``(project, view, sorted dataset ids, gold source, min grade)``. The TTL matches the
underlying probe cache (6h) so a stale result naturally ages out with the retrieval data it was
built from. Bump ``_VERSION`` to invalidate every cached result when the metric logic changes.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel

from app.cache import cache_get_json, cache_set_json

_RESULT_TTL = 21_600  # 6 hours, matching the probe cache
_VERSION = "v2"

TModel = TypeVar("TModel", bound=BaseModel)


def result_cache_key(
    project_id: UUID,
    view: str,
    dataset_ids: Iterable[UUID],
    gold_source: str,
    min_grade: int,
    include_agent: bool = False,
) -> str:
    """Cache key for one computed metrics response, stable across dataset-id ordering.

    ``include_agent`` (by-stage only) probes the external custom-agent endpoint as an extra stage;
    it changes the result, so it gets its own key. Kept as a suffix appended only when set, so the
    common (no-agent) keys stay byte-identical to before.
    """
    ids = ",".join(sorted(str(i) for i in dataset_ids))
    suffix = ":agent" if include_agent else ""
    return f"retrieval:metrics:{_VERSION}:{project_id}:{view}:{gold_source}:g{min_grade}:{ids}{suffix}"


async def get_cached(key: str, model: type[TModel]) -> TModel | None:
    """Return the cached response validated into ``model``, or None on miss/invalid payload."""
    cached = await cache_get_json(key)
    if cached is None:
        return None
    try:
        return model.model_validate(cached)
    except Exception:  # noqa: BLE001 — a stale/incompatible payload just misses the cache
        return None


async def store(key: str, result: TModel) -> TModel:
    """Stamp ``result.computed_at`` = now, cache it, and return the stamped copy."""
    stamped = result.model_copy(update={"computed_at": datetime.now(timezone.utc).isoformat()})
    await cache_set_json(key, stamped.model_dump(), ttl_seconds=_RESULT_TTL)
    return stamped
