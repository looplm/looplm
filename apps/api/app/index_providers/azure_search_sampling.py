"""Even-spaced sampling across a filtered slice of an Azure AI Search index.

Split out of ``azure_search`` to keep that module focused.

The plain sample path asks for the first ``n`` hits of a match-all filtered query.
Azure returns those in its own internal order (in practice roughly insertion order),
and chunks of one document sit next to each other, so a slice containing one large
document easily yields ``n`` chunks of that single document. For drill-down that is
harmless; for grounding an LLM it is the wrong sample, because the excerpts are meant
to describe the slice rather than whichever page was indexed first.

This module walks the slice at even offsets instead: the first request also asks for
the slice's total size, then the remaining offsets are spread across it. That costs
one request per returned chunk, so it is opt-in via
``sample_documents(..., spread=True)`` and used by the coverage worker rather than by
interactive drill-down.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.index_providers.base import CorpusDoc

if TYPE_CHECKING:
    from app.index_providers.azure_search import AzureSearchIndexProvider

logger = logging.getLogger(__name__)

# Azure rejects `$skip` beyond 100k; a slice bigger than that is sampled across the
# reachable window (the alternative — failing — would be worse than a partial spread).
MAX_SKIP = 100_000


def spread_offsets(total: int, n: int, max_skip: int = MAX_SKIP) -> list[int]:
    """Evenly spaced 0-based offsets into a slice holding ``total`` documents.

    Always starts at 0 and never repeats an offset. When ``n`` is at least the
    reachable size, every position is returned (no point spacing them out).
    """
    if n <= 1 or total <= 1:
        return [0]
    reachable = min(total, max_skip + 1)
    if n >= reachable:
        return list(range(reachable))
    step = reachable / n
    offsets: list[int] = []
    for i in range(n):
        offset = min(int(i * step), reachable - 1)
        if offset not in offsets:
            offsets.append(offset)
    return offsets


async def spread_sample(
    search_client, filter_expr: str | None, select: list[str] | None, n: int
) -> list[dict]:
    """Up to ``n`` raw documents spread evenly across the filtered slice.

    Issues one request per offset. Requests that fail (or return nothing, e.g. the
    slice shrank between calls) are skipped rather than aborting the sample, so a
    partial spread still reaches the caller.
    """
    if n <= 0:
        return []

    kwargs = {"search_text": "*", "filter": filter_expr, "select": select or None}

    first = await search_client.search(**kwargs, top=1, include_total_count=True)
    docs = [dict(d) async for d in first]
    total = int(await first.get_count() or 0)
    if not docs:
        return []

    for offset in spread_offsets(total, n)[1:]:
        try:
            page = await search_client.search(**kwargs, top=1, skip=offset)
            docs.extend([dict(d) async for d in page])
        except Exception:  # noqa: BLE001 — one lost offset must not lose the whole sample
            logger.warning("Spread sample failed at offset %d", offset, exc_info=True)
    return docs[:n]


async def sample_documents(
    provider: "AzureSearchIndexProvider",
    key: str,
    value: str,
    n: int,
    filters: dict[str, str] | None = None,
    *,
    spread: bool = False,
) -> list[CorpusDoc]:
    """``BaseIndexProvider.sample_documents`` for Azure (see that docstring)."""
    from app.index_providers.azure_search import _PREFERRED_SAMPLE_FIELDS, _odata_escape

    info = await provider._field(key)
    fields = await provider._get_fields()
    esc = _odata_escape(value)
    if info.is_collection:
        filter_expr = f"{key}/any(t: t eq '{esc}')"
    else:
        filter_expr = f"{key} eq '{esc}'"

    ancestor_expr = await provider._build_filter(filters)
    if ancestor_expr:
        filter_expr = f"({filter_expr}) and ({ancestor_expr})"

    select = [f for f in _PREFERRED_SAMPLE_FIELDS if f in fields]
    key_field = next((f.name for f in fields.values() if f.is_key), None)
    if key_field and key_field not in select:
        select.append(key_field)

    if spread:
        raw = await spread_sample(provider._search_client, filter_expr, select, max(1, n))
    else:
        results = await provider._search_client.search(
            search_text="*",
            filter=filter_expr,
            select=select or None,
            top=max(1, n),
        )
        raw = [dict(doc) async for doc in results]

    return [
        CorpusDoc(
            id=str(doc.get(key_field) or doc.get("page_id") or doc.get("id") or ""),
            title=doc.get("attachment_filename") or doc.get("page_title"),
            url=doc.get("page_url") or doc.get("attachment_url"),
            # Full chunk body, never truncated: every consumer either feeds it to an LLM
            # (where a cut-off chunk falsifies the judgement) or clamps it for display in
            # the UI. Truncating here would lose the tail for both.
            snippet=doc.get("chunk_text"),
        )
        for doc in raw
    ]
