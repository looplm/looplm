"""Reading well-known fields out of an index document, regardless of provider naming.

Providers name the same concept differently (``chunk_text`` vs ``content`` vs ``chunkText``), so
lookups go through priority-ordered field-name tuples plus small type-guarding readers. Kept in the
service layer (not under a router) so both the labeling routers and background services can share
them without importing each other.
"""

from __future__ import annotations

# Index fields that hold a chunk's full body, in priority order. Mirrors the web client's
# INDEX_TEXT_FIELDS (chunk-row.tsx) so the judge reads the same text "Show full chunk" renders.
INDEX_TEXT_FIELDS = ("chunk_text", "content", "text", "chunkText")

# Index fields that hold a chunk's heading/section context, in priority order. Used as the display
# grouping for the passage-selection panel (the section header labels the checkbox list).
INDEX_HEADING_FIELDS = ("heading_context", "headingContext", "section_path", "section", "headings")

# Index fields that hold a chunk's character start offset into the parsed document, in priority
# order. Emitted by the rde indexer's markdown/DI chunker (``chunk_char_start``); absent on legacy
# sliding-window chunker pages. Lets the passage split be anchored to document coordinates so a
# selection survives re-chunking (the *A+* path).
INDEX_CHAR_START_FIELDS = ("chunk_char_start", "char_start", "chunkCharStart")


def first_int_field(fields: dict, names: tuple[str, ...]) -> int | None:
    """First integer value among ``names`` in an index document, else None.

    Booleans are ``int`` subclasses in Python but never a valid offset, so they're skipped.
    """
    for name in names:
        v = fields.get(name)
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            return v
    return None


def first_str_field(fields: dict, names: tuple[str, ...]) -> str | None:
    """First non-empty string value among ``names`` in an index document, else None."""
    for name in names:
        v = fields.get(name)
        if isinstance(v, str) and v.strip():
            return v.strip()
        # Heading context is sometimes a list of ancestor headings; join it.
        if isinstance(v, (list, tuple)) and v:
            joined = " › ".join(str(p).strip() for p in v if str(p).strip())
            if joined:
                return joined
    return None
