"""Filename search and chunks-of-a-file listing for Azure AI Search.

Split out of ``azure_search`` to keep that module focused. These functions operate
on an :class:`AzureSearchIndexProvider` instance, reusing its cached field schema
and search client. They back the Data Sources "Files" tab: find files by name, then
list every chunk of one file in reading order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.index_providers.base import CorpusDoc, FileMatch
from app.index_providers.chunk_quality_common import (
    ORDINAL_FIELDS,
    PARENT_FIELDS,
    TEXT_FIELDS,
    pick_field,
)

if TYPE_CHECKING:
    from app.index_providers.azure_search import AzureSearchIndexProvider, _FieldInfo

# Field-name candidates for the filename search, in priority order. Attachments are
# identified by their filename; pages by a title. Detection is best-effort — the
# external index schema is not guaranteed to use these names.
_FILENAME_FIELDS = ["attachment_filename", "filename", "file_name"]
_PAGE_TITLE_FIELDS = ["page_title", "title", "heading", "document_title", "name"]
_PAGE_URL_FIELDS = ["page_url", "url", "source_url", "link", "uri"]

_FILE_SEARCH_TOP = 200  # hits scanned to discover distinct files
_MAX_FILE_CANDIDATES = 40  # cap the number of per-file count queries
_CHUNK_PAGE = 1000  # Azure's per-request `top` ceiling
_CHUNK_CAP = 2000  # upper bound on chunks returned for one file


def build_file_field_map(fields: dict[str, "_FieldInfo"]) -> dict[str, str | None]:
    """Detect the fields the filename feature needs, best-effort by name."""
    keys = set(fields.keys())
    return {
        "filename": pick_field(keys, _FILENAME_FIELDS),
        "page_title": pick_field(keys, _PAGE_TITLE_FIELDS),
        "parent": pick_field(keys, PARENT_FIELDS),
        "ordinal": pick_field(keys, ORDINAL_FIELDS),
        "text": pick_field(keys, TEXT_FIELDS),
        "page_url": pick_field(keys, _PAGE_URL_FIELDS),
        "attachment_url": pick_field(keys, ["attachment_url"]),
        "key": next((fi.name for fi in fields.values() if fi.is_key), None),
    }


def _ordinal_key(value) -> float:
    """Numeric sort key for a chunk ordinal; non-numeric sorts last (stable)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


_HEX = set("0123456789abcdef")


def _looks_like_hashed_page_id(value: str) -> bool:
    """True for a scraped/external page id vs a Confluence one.

    The rde indexer derives external page ids as ``sha1(url)[:16]`` (16 hex chars),
    while Confluence Cloud page ids are all-numeric — the one clean signal that
    separates the two (source_type/tags don't). Require an alpha hex digit so an
    all-numeric Confluence id can't false-positive.
    """
    v = value.lower()
    return len(v) == 16 and all(c in _HEX for c in v) and any(c in "abcdef" for c in v)


async def _filter_for(provider: "AzureSearchIndexProvider", field_name: str, value: str) -> str:
    """Collection-aware ``field eq value`` OData clause (mirrors sample_documents)."""
    from app.index_providers.azure_search import _odata_escape

    info = await provider._field(field_name)
    esc = _odata_escape(value)
    if info.is_collection:
        return f"{field_name}/any(t: t eq '{esc}')"
    return f"{field_name} eq '{esc}'"


async def _count_for(provider: "AzureSearchIndexProvider", field_name: str, value: str) -> int:
    results = await provider._search_client.search(
        search_text="*",
        filter=await _filter_for(provider, field_name, value),
        top=0,
        include_total_count=True,
    )
    return int(await results.get_count() or 0)


async def search_files(
    provider: "AzureSearchIndexProvider", query: str, limit: int
) -> list[FileMatch]:
    f = await provider._file_field_map()
    search_fields = [x for x in (f["filename"], f["page_title"]) if x]
    if not search_fields:
        return []

    select = [
        x
        for x in (
            f["filename"], f["page_title"], f["parent"], f["page_url"], f["attachment_url"], f["key"]
        )
        if x
    ]
    # Prefix wildcard so partial names match (e.g. "invoice" → invoice_2024.pdf).
    results = await provider._search_client.search(
        search_text=f"{query.strip()}*",
        search_fields=search_fields,
        select=select or None,
        top=_FILE_SEARCH_TOP,
    )

    # Dedupe hits into distinct files. An attachment (has a filename) groups by its
    # filename; anything else is a page, grouped by its parent id (falling back to the
    # title) and labelled by the title.
    seen: dict[tuple, FileMatch] = {}
    async for doc in results:
        # The document's real title, carried separately from ``label`` so a caller
        # matching by name can score against it even when ``label`` is a numeric
        # attachment filename.
        ptitle = (f["page_title"] and doc.get(f["page_title"])) or None
        fname = f["filename"] and doc.get(f["filename"])
        if fname:
            key, value, label, kind = f["filename"], str(fname), str(fname), "attachment"
            url = doc.get(f["attachment_url"]) if f["attachment_url"] else None
        else:
            title = (f["page_title"] and doc.get(f["page_title"])) or ""
            url = doc.get(f["page_url"]) if f["page_url"] else None
            # Group pages by the most stable identifier that has a *value* on this
            # doc: a parent id (Confluence page_id), else the URL (scraped web
            # pages have a URL but often no page_id), else the title.
            group_field, raw = None, None
            for candidate in (f["parent"], f["page_url"], f["page_title"]):
                if candidate and doc.get(candidate):
                    group_field, raw = candidate, doc.get(candidate)
                    break
            if not raw:
                continue
            value = str(raw)
            # A scraped/external web page (hashed page_id) vs a Confluence page.
            kind = "web" if group_field == f["parent"] and _looks_like_hashed_page_id(value) else "page"
            key, label = group_field, str(title or raw)
        dedupe = (kind, key, value)
        if dedupe not in seen:
            seen[dedupe] = FileMatch(
                key=key, value=value, label=label, kind=kind, chunk_count=0, url=url,
                page_title=str(ptitle) if ptitle else None,
            )
        if len(seen) >= _MAX_FILE_CANDIDATES:
            break

    for match in seen.values():
        match.chunk_count = await _count_for(provider, match.key, match.value)
    matches = sorted(seen.values(), key=lambda m: m.chunk_count, reverse=True)
    return matches[: max(1, limit)]


async def list_file_chunks(
    provider: "AzureSearchIndexProvider",
    key: str,
    value: str,
    kind: str,
    limit: int,
    *,
    include_text: bool = True,
) -> list[CorpusDoc]:
    f = await provider._file_field_map()
    filter_expr = await _filter_for(provider, key, value)
    # The bulk completeness scan only needs ordinals + counts, so it drops the
    # (large) chunk text field from the projection to keep the scan cheap.
    text_field = f["text"] if include_text else None
    select = [
        x
        for x in (
            text_field, f["ordinal"], f["filename"], f["page_title"],
            f["page_url"], f["attachment_url"], f["parent"], f["key"], key,
        )
        if x
    ]

    cap = min(max(1, limit), _CHUNK_CAP)  # a single file's chunks are bounded
    docs: list[CorpusDoc] = []
    skip = 0
    while len(docs) < cap and skip < 100_000:
        results = await provider._search_client.search(
            search_text="*",
            filter=filter_expr,
            select=select or None,
            top=min(_CHUNK_PAGE, cap - len(docs)),
            skip=skip,
        )
        page = 0
        async for doc in results:
            page += 1
            # Full chunk text (not truncated): this view is for reading a file's
            # chunks in order, so the whole text is shown. Omitted entirely when
            # the caller opted out (the bulk scan).
            snippet = doc.get(text_field) if text_field else None
            docs.append(
                CorpusDoc(
                    id=str(
                        (f["key"] and doc.get(f["key"]))
                        or (f["parent"] and doc.get(f["parent"]))
                        or doc.get("id")
                        or ""
                    ),
                    title=(f["filename"] and doc.get(f["filename"]))
                    or (f["page_title"] and doc.get(f["page_title"])),
                    url=(f["page_url"] and doc.get(f["page_url"]))
                    or (f["attachment_url"] and doc.get(f["attachment_url"])),
                    snippet=snippet,
                    ordinal=doc.get(f["ordinal"]) if f["ordinal"] else None,
                )
            )
        if page == 0:
            break
        skip += page

    # Reading order: sort by the ordinal field when the index has one. Done in Python
    # (not Azure ``orderby``) because the field is not guaranteed sortable; a single
    # file's chunk set is bounded, so this is cheap.
    if f["ordinal"]:
        docs.sort(key=lambda d: _ordinal_key(d.ordinal))
    return docs
