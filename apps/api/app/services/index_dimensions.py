"""Provider-agnostic readers for the "what is in the index" dimensions.

Extracted from ``routers/index_explorer.py`` so the Overview page and the Data Sources
drill-down share one detection rule. Without this they would drift, and the router had
already grown past the 500-line limit.
"""

from __future__ import annotations

from app.index_providers.chunk_quality_common import pick_field

# File-type dimension candidates, in priority order. Detected among the index's
# *facetable* fields, since the distribution is computed by faceting on it.
FILETYPE_FIELDS = [
    "content_type", "doc_type", "file_type", "mimetype", "mime_type",
    "format", "source_type", "type",
]


async def file_type_distribution(client) -> tuple[str | None, list[tuple[str, int]]]:
    """(detected field, [(value, chunk_count)]) for the index behind ``client``.

    Returns ``(None, [])`` when the index exposes no suitable facetable type field.
    The caller owns the client lifecycle and error translation, because the two callers
    want different failure behavior: the drill-down raises 502, the Overview degrades.
    """
    keys = await client.list_partition_keys()
    field = pick_field({k.key for k in keys}, FILETYPE_FIELDS)
    if field is None:
        return None, []
    values = await client.get_partition_distribution(field)
    return field, [(v.value, v.doc_count) for v in values]
