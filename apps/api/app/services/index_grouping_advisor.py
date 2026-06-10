"""LLM-backed grouping advisor for the Data Sources index explorer.

The explorer lets a user group a connected retrieval index by an ordered list of
facetable metadata fields. Picking those fields by hand is hard: an index can
expose dozens of fields, and some fields' *values* are near-unique (URLs) or
encode an entire breadcrumb path inside a single string — both make terrible
grouping dimensions.

This service profiles every facetable field (cardinality + sample values +
cheap heuristics), asks the shared :class:`AnalysisLlmService` to choose a sane
hierarchy, and returns it together with metadata-quality hints (e.g. "split this
path-encoded field" / "add a source_type field"). It mirrors the LLM-call and
usage-tracking shape of ``services/architecture_advisor.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.index_providers.base import BaseIndexProvider, PartitionKey, PartitionValue
from app.schemas.index_explorer import (
    GroupingLevel,
    IndexGroupingSuggestion,
    MetadataHint,
)

logger = logging.getLogger(__name__)

# Bound the work: profile at most this many fields and sample this many values.
_MAX_FIELDS = 40
_TOP_VALUES = 15
_FACET_CAP = 1000  # mirrors AzureSearchIndexProvider._MAX_FACET_VALUES
_DOMINANT_RATIO = 0.95
# Tokens that signal a value encodes a delimited path rather than a flat label.
_PATH_MARKERS = (" > ", " / ", " \\ ", ">", "\\")

_SYSTEM_PROMPT = (
    "You are a data-architecture assistant for a retrieval-index explorer. "
    "Given a profile of an index's facetable metadata fields, design the most "
    "intuitive way to browse the corpus as a drill-down tree, and flag metadata "
    "problems. Respond with a single valid JSON object only."
)


def _looks_like_path(values: list[PartitionValue]) -> bool:
    """True when sampled values look like delimited paths/breadcrumbs."""
    sample = [v.value for v in values[:_TOP_VALUES] if v.value]
    if not sample:
        return False
    hits = sum(1 for s in sample if any(m in s for m in (" > ", " / ", " \\ ")))
    return hits >= max(1, len(sample) // 2)


def _profile_key(key: PartitionKey, values: list[PartitionValue], doc_count: int) -> dict:
    """Compact, LLM-friendly profile of one facetable field."""
    distinct = len(values)
    top = values[:_TOP_VALUES]
    lengths = [len(v.value) for v in top if v.value]
    avg_len = round(sum(lengths) / len(lengths)) if lengths else 0
    dominant = bool(top and doc_count and top[0].doc_count >= _DOMINANT_RATIO * doc_count)
    return {
        "key": key.key,
        "label": key.label,
        "type": str(key.metadata.get("type", "")),
        "multivalued": key.multivalued,
        "distinct_values": f">={_FACET_CAP}" if distinct >= _FACET_CAP else distinct,
        "avg_value_length": avg_len,
        "looks_like_path": _looks_like_path(values),
        "single_dominant_value": dominant,
        "top_values": [{"value": v.value, "count": v.doc_count} for v in top],
    }


def _build_prompt(doc_count: int, profiles: list[dict]) -> str:
    return (
        f"The index holds {doc_count:,} documents. Below is a JSON profile of each "
        "facetable field — its cardinality, a sample of its most common values with "
        "counts, and heuristics (looks_like_path, single_dominant_value).\n\n"
        f"{json.dumps(profiles, ensure_ascii=False, indent=2)}\n\n"
        "Design a drill-down hierarchy a human would find intuitive:\n"
        "- Put low-to-moderate cardinality categorical fields near the top, "
        "higher-cardinality fields deeper.\n"
        "- NEVER use a near-unique field (distinct_values close to the document "
        "count) or a field where looks_like_path is true as a grouping dimension — "
        "those are document identifiers/leaves, not groups.\n"
        "- Use at most 4 levels. Prefer fewer if that reads more clearly.\n"
        "- Skip fields with a single_dominant_value (they add no signal).\n\n"
        "Also emit hints about metadata quality:\n"
        '- For a field whose values encode a delimited path, add a "warning" hint '
        'recommending the index be re-indexed with that path split into separate '
        'fields (e.g. level_1, level_2), and set "suggested_field".\n'
        '- If no good top-level categorical dimension exists (e.g. no source/type '
        'field), add a hint recommending one be added, with "suggested_field".\n'
        "- Keep hints short and actionable.\n\n"
        "Respond with JSON of exactly this shape:\n"
        "{\n"
        '  "suggested_group_by": ["field_key", ...],  // ordered, top to bottom\n'
        '  "summary": "one sentence explaining the hierarchy",\n'
        '  "levels": [{"key": "field_key", "label": "...", "reason": "why this level"}],\n'
        '  "hints": [{"severity": "info|warning", "title": "...", "message": "...", '
        '"field": "existing_key_or_null", "suggested_field": "new_field_or_null"}]\n'
        "}\n"
        "Use only field keys that appear in the profile above for suggested_group_by "
        "and levels[].key."
    )


def _parse(raw: str, valid_keys: list[str]) -> IndexGroupingSuggestion:
    """Parse + sanitize the LLM JSON into a validated suggestion.

    Clamps ``suggested_group_by`` (and ``levels``) to fields that actually exist
    and dedupes them; falls back to the first available key when the result is
    empty. Defensive against hallucinated field names.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Grouping advisor returned non-JSON output")
        data = {}

    valid = set(valid_keys)
    seen: set[str] = set()
    group_by: list[str] = []
    for k in data.get("suggested_group_by", []) or []:
        if isinstance(k, str) and k in valid and k not in seen:
            seen.add(k)
            group_by.append(k)
    if not group_by and valid_keys:
        group_by = [valid_keys[0]]

    levels: list[GroupingLevel] = []
    for lvl in data.get("levels", []) or []:
        if not isinstance(lvl, dict):
            continue
        key = lvl.get("key")
        if isinstance(key, str) and key in group_by:
            levels.append(
                GroupingLevel(
                    key=key,
                    label=str(lvl.get("label") or key),
                    reason=str(lvl.get("reason") or ""),
                )
            )

    hints: list[MetadataHint] = []
    for h in data.get("hints", []) or []:
        if not isinstance(h, dict):
            continue
        severity = h.get("severity")
        if severity not in ("info", "warning"):
            severity = "info"
        title = str(h.get("title") or "").strip()
        message = str(h.get("message") or "").strip()
        if not title and not message:
            continue
        hints.append(
            MetadataHint(
                severity=severity,
                title=title or "Metadata hint",
                message=message,
                field=(h.get("field") or None),
                suggested_field=(h.get("suggested_field") or None),
            )
        )

    return IndexGroupingSuggestion(
        suggested_group_by=group_by,
        summary=str(data.get("summary") or ""),
        levels=levels,
        hints=hints,
    )


async def suggest_grouping(
    client: BaseIndexProvider,
    *,
    project_id: UUID,
    db: AsyncSession,
    user_settings: dict | None = None,
) -> tuple[IndexGroupingSuggestion, str]:
    """Profile the index and return (suggestion, llm_model).

    The caller owns the provider ``client`` lifecycle (open + ``aclose``).
    """
    from app.services.analysis_llm import AnalysisLlmService
    from app.services.llm_usage_tracker import record_llm_usage

    doc_count = await client.test_connection()
    keys = (await client.list_partition_keys())[:_MAX_FIELDS]
    if not keys:
        return IndexGroupingSuggestion(summary="This index exposes no groupable fields."), ""

    # Fetch each field's value distribution concurrently (Azure facets are cheap).
    distributions = await asyncio.gather(
        *(client.get_partition_distribution(k.key) for k in keys),
        return_exceptions=True,
    )
    profiles: list[dict] = []
    valid_keys: list[str] = []
    for key, dist in zip(keys, distributions):
        if isinstance(dist, BaseException):
            logger.warning("Skipping field %s in grouping profile: %s", key.key, dist)
            continue
        valid_keys.append(key.key)
        profiles.append(_profile_key(key, dist, doc_count))

    if not profiles:
        return IndexGroupingSuggestion(summary="Could not profile any index fields."), ""

    llm = AnalysisLlmService(user_settings=user_settings)
    raw, usage = await llm.tracked_chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(doc_count, profiles)},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    await record_llm_usage(
        db,
        project_id=project_id,
        service_name="index_grouping_advisor",
        function_name="suggest_grouping",
        provider=llm.provider,
        model=llm.model,
        usage=usage,
    )

    return _parse(raw, valid_keys), llm.model
