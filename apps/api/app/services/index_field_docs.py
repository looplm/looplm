"""LLM-backed field-documentation generator for the Data Sources "Fields" tab.

An index can expose dozens of metadata fields whose names are terse and whose
purposes overlap in confusing ways: ``page_url`` vs ``attachment_url``,
``source_type`` vs ``content_type``, ``page_id`` vs ``chunk_index``. This service
profiles the index schema (each field's type, capability flags, sampled example
values, and fill rate) and asks the shared :class:`AnalysisLlmService` to write,
for every field, a one-line purpose, plus groups of related/confusable fields
each with the distinction between them.

Mirrors the LLM-call and usage-tracking shape of ``index_grouping_advisor.py``.
The result is cached on the ``IndexProvider`` row and recomputed on demand.
"""

from __future__ import annotations

import json
import logging
import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.index_providers.base import BaseIndexProvider, FieldSchema
from app.schemas.index_explorer import (
    IndexFieldDoc,
    IndexFieldDocs,
    IndexFieldGroup,
)

logger = logging.getLogger(__name__)

# Bound the work: document at most this many fields per call.
_MAX_FIELDS = 80
_FIELD_SCHEMA_SAMPLE = 50  # docs sampled to derive example values

_SYSTEM_PROMPT = (
    "You are a data-architecture assistant for a retrieval-index explorer. "
    "Given the schema of a search index (field names, types, capability flags, "
    "sampled example values, and fill rates), explain what each field is for and "
    "clarify how easily-confused fields differ from one another. Base every claim "
    "on the evidence provided; do not invent fields or attributes. Respond with a "
    "single valid JSON object only. Never use em dashes (the — character) "
    "anywhere in your text; use commas or periods instead."
)

_EM_DASH = re.compile(r"\s*—\s*")


def _no_em_dash(text: str) -> str:
    """Replace em dashes (and surrounding spaces) with a comma. Belt-and-braces
    on top of the prompt instruction, since models love an em dash."""
    return _EM_DASH.sub(", ", text).strip().rstrip(",").strip()


def _attr_flags(f: FieldSchema) -> list[str]:
    flags: list[str] = []
    if f.is_key:
        flags.append("key")
    if f.searchable:
        flags.append("searchable")
    if f.filterable:
        flags.append("filterable")
    if f.facetable:
        flags.append("facetable")
    if f.sortable:
        flags.append("sortable")
    if not f.retrievable:
        flags.append("not-retrievable")
    if f.is_vector:
        flags.append("vector")
    return flags


def _profile_field(f: FieldSchema) -> dict:
    """Compact, LLM-friendly profile of one index field."""
    return {
        "name": f.name,
        "type": f.type,
        "multivalued": f.is_collection,
        "attributes": _attr_flags(f),
        "fill_rate": f.fill_rate,
        "example_values": f.example_values,
    }


def _build_prompt(profiles: list[dict]) -> str:
    return (
        "Below is a JSON profile of each field in a retrieval index: its type, "
        "whether it is multivalued, its capability attributes (key, searchable, "
        "filterable, facetable, sortable, not-retrievable, vector), the fraction "
        "of sampled documents that carry a value (fill_rate), and a few example "
        "values.\n\n"
        f"{json.dumps(profiles, ensure_ascii=False, indent=2)}\n\n"
        "Do two things:\n"
        "1. For EVERY field, write a single concise sentence describing what it "
        "holds and what it is used for. Ground it in the example values and "
        "attributes (e.g. a searchable-only field is meant for full-text matching; "
        "a filterable+facetable field is a browsing dimension; a vector field is an "
        "embedding). Keep it plain and specific; avoid restating the field name.\n"
        "2. Identify GROUPS of fields that are easy to confuse with each other "
        "(near-synonyms, overlapping roles, or the same concept at different "
        "granularity, e.g. a page URL vs an attachment URL, a source type vs a "
        "content type, a document id vs a chunk ordinal). For each group, explain "
        "in one or two sentences how the fields differ and when each applies. Only "
        "group fields that genuinely risk being mixed up; skip singletons.\n\n"
        "Respond with JSON of exactly this shape:\n"
        "{\n"
        '  "summary": "one sentence describing what this index stores overall",\n'
        '  "fields": [{"name": "field_key", "purpose": "one sentence"}],\n'
        '  "groups": [{"title": "short label", "field_names": ["a", "b"], '
        '"distinction": "how they differ"}]\n'
        "}\n"
        "Use only field names that appear in the profile above. Do not use em dashes."
    )


def _parse(raw: str, valid_names: list[str]) -> IndexFieldDocs:
    """Parse + sanitize the LLM JSON into validated field docs.

    Clamps field references to names that actually exist, dedupes per-field
    purposes, drops groups with fewer than two valid fields, and strips em
    dashes. Defensive against hallucinated field names.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Field-docs advisor returned non-JSON output")
        data = {}

    valid = set(valid_names)
    seen: set[str] = set()
    fields: list[IndexFieldDoc] = []
    for item in data.get("fields", []) or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        purpose = _no_em_dash(str(item.get("purpose") or ""))
        if not isinstance(name, str) or name not in valid or name in seen or not purpose:
            continue
        seen.add(name)
        fields.append(IndexFieldDoc(name=name, purpose=purpose))

    groups: list[IndexFieldGroup] = []
    for g in data.get("groups", []) or []:
        if not isinstance(g, dict):
            continue
        raw_names = g.get("field_names") or g.get("fields") or []
        if not isinstance(raw_names, list):
            continue
        names: list[str] = []
        for n in raw_names:
            if isinstance(n, str) and n in valid and n not in names:
                names.append(n)
        distinction = _no_em_dash(str(g.get("distinction") or g.get("message") or ""))
        if len(names) < 2 or not distinction:
            continue
        groups.append(
            IndexFieldGroup(
                title=_no_em_dash(str(g.get("title") or "")) or "Related fields",
                field_names=names,
                distinction=distinction,
            )
        )

    return IndexFieldDocs(
        summary=_no_em_dash(str(data.get("summary") or "")),
        fields=fields,
        groups=groups,
    )


async def explain_fields(
    client: BaseIndexProvider,
    *,
    project_id: UUID,
    db: AsyncSession,
    user_settings: dict | None = None,
) -> tuple[IndexFieldDocs, str]:
    """Profile the index schema and return (field_docs, llm_model).

    The caller owns the provider ``client`` lifecycle (open + ``aclose``).
    """
    from app.services.analysis_llm import AnalysisLlmService
    from app.services.llm_usage_tracker import record_llm_usage

    schema = (await client.get_field_schema(sample_size=_FIELD_SCHEMA_SAMPLE))[:_MAX_FIELDS]
    if not schema:
        return IndexFieldDocs(summary="This index exposes no fields."), ""

    valid_names = [f.name for f in schema]
    profiles = [_profile_field(f) for f in schema]

    llm = AnalysisLlmService(user_settings=user_settings)
    raw, usage = await llm.tracked_chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(profiles)},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    await record_llm_usage(
        db,
        project_id=project_id,
        service_name="index_field_docs",
        function_name="explain_fields",
        provider=llm.provider,
        model=llm.model,
        usage=usage,
    )

    return _parse(raw, valid_names), llm.model
