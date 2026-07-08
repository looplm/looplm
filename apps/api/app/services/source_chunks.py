"""Resolve a wanted source to its indexed chunks, in reading order.

Backs the Data Sources "Source review" tab: for one ``SourceExpectation`` it
finds the source's file in the index and returns every chunk in reading order,
so a reviewer can page through them and eyeball completeness.

Resolution reuses the gap-analysis matching (kept in ``source_gaps``):

1. **URL hash** — the rde indexer derives ``page_id = sha1(canonical_url)[:16]``,
   so a source with a direct document URL is resolved exactly via a bulk id
   lookup (either the HTML page or its PDF twin counts).
2. **Title search** — otherwise fall back to a filename/title search for the
   source name and take the best-overlapping distinct file.

Once resolved to a ``(field, value, kind)`` file handle, chunk listing reuses
the provider's ``list_file_chunks`` (the same path the "Files" tab uses).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.index_providers.base import BaseIndexProvider, CorpusDoc
from app.index_providers.source_gaps import (
    WEAK_TITLE_OVERLAP,
    page_id_for,
    title_overlap,
)

# Cap the reported missing-ordinal list so a source with a sparse/large ordinal
# field (e.g. page numbers) can't produce a huge payload.
_MAX_REPORTED_GAPS = 200


@dataclass
class SourceChunkInput:
    """The slice of a SourceExpectation the resolver needs (ORM-free)."""

    id: str
    name: str
    html_url: str | None = None
    pdf_url: str | None = None
    adapter_tag: str | None = None


@dataclass
class SourceChunksResult:
    resolved: bool
    resolution: str  # "url" | "title" | "none"
    kind: str | None = None
    matched_title: str | None = None
    matched_url: str | None = None
    chunk_count: int = 0
    ordinal_available: bool = False
    missing_ordinals: list[int] = field(default_factory=list)
    duplicate_ordinals: list[int] = field(default_factory=list)
    gaps_truncated: bool = False
    chunks: list[CorpusDoc] = field(default_factory=list)


@dataclass
class _Handle:
    key: str
    value: str
    kind: str
    matched_url: str | None
    matched_title: str | None
    resolution: str  # "url" | "title"


async def _resolve_handle(
    provider: BaseIndexProvider, source: SourceChunkInput, *, id_field: str = "page_id"
) -> _Handle | None:
    """Locate the source's file in the index; None when nothing matches."""
    # Strategy 1: exact URL-hash hit on either variant.
    for url in (source.html_url, source.pdf_url):
        if not url:
            continue
        pid = page_id_for(url)
        try:
            counts = await provider.lookup_ids(id_field, [pid])
        except NotImplementedError:
            counts = {}
        if counts.get(pid, 0) > 0:
            return _Handle(
                key=id_field, value=pid, kind="web", matched_url=url,
                matched_title=None, resolution="url",
            )

    # Strategy 2: filename/title search for the source name; best distinct file.
    try:
        matches = await provider.search_files(source.name, 10)
    except NotImplementedError:
        matches = []
    best, best_score = None, 0.0
    for m in matches:
        # Score against every human-readable handle the match carries: the display
        # label (a filename for attachments), the real document title, and the URL.
        # Mirrors the gap-analysis matcher, which scores title AND url. Without
        # page_title, every attachment whose filename is a numeric id (the entire
        # external/MAKO corpus) scores 0 against its real name and is falsely
        # reported "not in index".
        score = max(title_overlap(source.name, c) for c in (m.label, m.page_title, m.url) if c)
        if score > best_score:
            best, best_score = m, score
    if best is not None and best_score >= WEAK_TITLE_OVERLAP:
        return _Handle(
            key=best.key, value=best.value, kind=best.kind, matched_url=best.url,
            matched_title=best.page_title or best.label, resolution="title",
        )
    return None


def _ordinal_of(doc: CorpusDoc) -> int | None:
    try:
        return int(float(doc.ordinal))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _ordinal_gaps(docs: list[CorpusDoc]) -> tuple[bool, list[int], list[int], bool]:
    """(ordinal_available, missing, duplicate, truncated) over integer ordinals."""
    ordinals = [o for o in (_ordinal_of(d) for d in docs) if o is not None]
    if not ordinals:
        return False, [], [], False
    counts: dict[int, int] = {}
    for o in ordinals:
        counts[o] = counts.get(o, 0) + 1
    duplicate = sorted(o for o, c in counts.items() if c > 1)
    present = set(ordinals)
    missing = [i for i in range(min(ordinals), max(ordinals) + 1) if i not in present]
    truncated = len(missing) > _MAX_REPORTED_GAPS
    return True, missing[:_MAX_REPORTED_GAPS], duplicate, truncated


@dataclass
class SourceScanVerdict:
    """Compact per-source scan verdict (no chunk text) for the bulk scan."""

    resolved: bool
    resolution: str  # "url" | "title" | "none"
    kind: str | None = None
    matched_url: str | None = None
    matched_title: str | None = None
    chunk_count: int = 0
    missing_chunk_count: int = 0
    ordinal_checked: bool = False


async def scan_source(
    provider: BaseIndexProvider, source: SourceChunkInput, limit: int = 2000
) -> SourceScanVerdict:
    """Resolve ``source`` and summarise its indexed chunks — without the text.

    The bulk completeness scan calls this per source; it deliberately fetches
    ordinals only (``include_text=False``) so scanning hundreds of sources does
    not pull megabytes of chunk bodies. Raises on provider/transport failures so
    the caller's retry/backoff can act; a truly unresolved source is not an error
    (``resolved=False``).
    """
    handle = await _resolve_handle(provider, source)
    if handle is None:
        return SourceScanVerdict(resolved=False, resolution="none")
    docs = await provider.list_file_chunks(
        handle.key, handle.value, handle.kind, limit, include_text=False
    )
    ordinal_available, missing, _duplicate, _truncated = _ordinal_gaps(docs)
    return SourceScanVerdict(
        resolved=True,
        resolution=handle.resolution,
        kind=handle.kind,
        matched_url=handle.matched_url,
        matched_title=handle.matched_title,
        chunk_count=len(docs),
        missing_chunk_count=len(missing),
        ordinal_checked=ordinal_available,
    )


async def get_source_chunks(
    provider: BaseIndexProvider, source: SourceChunkInput, limit: int = 500
) -> SourceChunksResult:
    """Resolve ``source`` to a file in the index and list its chunks in order."""
    handle = await _resolve_handle(provider, source)
    if handle is None:
        return SourceChunksResult(resolved=False, resolution="none")

    docs = await provider.list_file_chunks(handle.key, handle.value, handle.kind, limit)
    ordinal_available, missing, duplicate, truncated = _ordinal_gaps(docs)
    return SourceChunksResult(
        resolved=True,
        resolution=handle.resolution,
        kind=handle.kind,
        matched_title=handle.matched_title,
        matched_url=handle.matched_url,
        chunk_count=len(docs),
        ordinal_available=ordinal_available,
        missing_ordinals=missing,
        duplicate_ordinals=duplicate,
        gaps_truncated=truncated,
        chunks=docs,
    )
