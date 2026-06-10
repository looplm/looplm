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
import re
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
    "problems. Respond with a single valid JSON object only. "
    "Never use em dashes (the — character) anywhere in your text; use commas or "
    "periods instead."
)

_EM_DASH = re.compile(r"\s*—\s*")


def _no_em_dash(text: str) -> str:
    """Replace em dashes (and surrounding spaces) with a comma. Belt-and-braces
    on top of the prompt instruction, since models love an em dash."""
    return _EM_DASH.sub(", ", text).strip().rstrip(",").strip()


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
    # Fraction of the corpus that carries any value for this field. Well below
    # 1.0 means the field only describes a subset (a parallel-facet candidate);
    # multivalued fields can exceed 1.0 since one doc has several values.
    covered = sum(v.doc_count for v in values)
    coverage = round(covered / doc_count, 2) if doc_count else 0.0
    return {
        "key": key.key,
        "label": key.label,
        "type": str(key.metadata.get("type", "")),
        "multivalued": key.multivalued,
        "distinct_values": f">={_FACET_CAP}" if distinct >= _FACET_CAP else distinct,
        "coverage_ratio": coverage,
        "avg_value_length": avg_len,
        "looks_like_path": _looks_like_path(values),
        "single_dominant_value": dominant,
        "top_values": [{"value": v.value, "count": v.doc_count} for v in top],
    }


def _build_prompt(doc_count: int, profiles: list[dict]) -> str:
    return (
        f"The index holds {doc_count:,} documents. Below is a JSON profile of each "
        "facetable field: its cardinality, coverage_ratio (fraction of the corpus "
        "that has any value for it), a sample of its most common values with counts, "
        "and heuristics (looks_like_path, single_dominant_value).\n\n"
        f"{json.dumps(profiles, ensure_ascii=False, indent=2)}\n\n"
        "Design a drill-down hierarchy a human would find intuitive. The hierarchy "
        "is a list of LEVELS, ordered top to bottom. Each level holds one or more "
        "field keys:\n"
        "- A level with ONE field nests normally (its value buckets become the "
        "parents of the next level).\n"
        "- A level with SEVERAL fields shows them as PARALLEL facets, side by side, "
        "not nested in each other.\n\n"
        "Rules:\n"
        "- Put low-to-moderate cardinality categorical fields near the top, "
        "higher-cardinality fields deeper.\n"
        "- NEVER use a near-unique field (distinct_values close to the document "
        "count) or a field where looks_like_path is true as a grouping dimension; "
        "those are document identifiers/leaves, not groups.\n"
        "- Skip fields with a single_dominant_value (they add no signal).\n"
        "- IMPORTANT: when two or more fields are ALTERNATIVE organizational schemes "
        "for DIFFERENT subsets of the corpus (each has a partial coverage_ratio and "
        "they describe complementary parts, e.g. one field tags some folders while "
        "another assigns a team to other folders), DO NOT nest them. Put them "
        "together in the SAME level as parallel facets.\n"
        "- Use at most 4 levels total. Prefer fewer if that reads more clearly.\n\n"
        "Also emit hints about metadata quality:\n"
        '- For a field whose values encode a delimited path, add a "warning" hint '
        "recommending the index be re-indexed with that path split into separate "
        'fields (e.g. level_1, level_2), and set "suggested_field".\n'
        "- If no good top-level categorical dimension exists (e.g. no source/type "
        'field), add a hint recommending one be added, with "suggested_field".\n'
        "- Keep hints short and actionable. Do not use em dashes.\n\n"
        "Respond with JSON of exactly this shape:\n"
        "{\n"
        '  "suggested_levels": [["field_key"], ["field_a", "field_b"], ...],\n'
        '  "summary": "one sentence explaining the hierarchy",\n'
        '  "levels": [{"keys": ["field_key"], "reason": "why this level"}],\n'
        '  "hints": [{"severity": "info|warning", "title": "...", "message": "...", '
        '"field": "existing_key_or_null", "suggested_field": "new_field_or_null"}]\n'
        "}\n"
        "Use only field keys that appear in the profile above."
    )


def _parse(raw: str, valid_keys: list[str]) -> IndexGroupingSuggestion:
    """Parse + sanitize the LLM JSON into a validated suggestion.

    Clamps ``suggested_levels`` (and ``levels``) to fields that actually exist,
    dedupes globally (a field appears in at most one level), drops empty levels,
    and falls back to a single level of the first available key when empty.
    Strips em dashes. Defensive against hallucinated field names.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Grouping advisor returned non-JSON output")
        data = {}

    # Tolerate either the parallel shape or the older flat one.
    raw_levels = data.get("suggested_levels")
    if raw_levels is None:
        raw_levels = [[k] for k in (data.get("suggested_group_by") or [])]

    valid = set(valid_keys)
    seen: set[str] = set()
    suggested_levels: list[list[str]] = []
    for lvl in raw_levels or []:
        fields = [lvl] if isinstance(lvl, str) else lvl
        if not isinstance(fields, list):
            continue
        keep: list[str] = []
        for k in fields:
            if isinstance(k, str) and k in valid and k not in seen:
                seen.add(k)
                keep.append(k)
        if keep:
            suggested_levels.append(keep)
    if not suggested_levels and valid_keys:
        suggested_levels = [[valid_keys[0]]]

    chosen = {k for lvl in suggested_levels for k in lvl}
    levels: list[GroupingLevel] = []
    for lvl in data.get("levels", []) or []:
        if not isinstance(lvl, dict):
            continue
        keys = lvl.get("keys")
        if keys is None and isinstance(lvl.get("key"), str):
            keys = [lvl["key"]]
        if not isinstance(keys, list):
            continue
        kept = [k for k in keys if isinstance(k, str) and k in chosen]
        if kept:
            levels.append(GroupingLevel(keys=kept, reason=_no_em_dash(str(lvl.get("reason") or ""))))

    hints: list[MetadataHint] = []
    for h in data.get("hints", []) or []:
        if not isinstance(h, dict):
            continue
        severity = h.get("severity")
        if severity not in ("info", "warning"):
            severity = "info"
        title = _no_em_dash(str(h.get("title") or ""))
        message = _no_em_dash(str(h.get("message") or ""))
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
        suggested_levels=suggested_levels,
        summary=_no_em_dash(str(data.get("summary") or "")),
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
