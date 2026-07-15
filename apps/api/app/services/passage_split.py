"""Split a pooled chunk's own text into sentence-level passages — the *A* passage source.

Passage labeling grades finer units than a chunk: a sentence, list item, or table row a labeler
can "uncheck" when it doesn't help answer the query. The preferred source (*B*) is stable,
offset-anchored sentence sub-passages derived by the rde indexer, whose ids survive re-chunking.
When those aren't available (no rde-derived passages for the page, or rde unreachable), we fall
back here: split the pooled chunk's ``chunk_text`` locally into sentence/line passages under its
heading context. These ids are chunk-derived (``{chunk_id}#s{n}``) so they orphan when the index
is re-chunked — acceptable for the fallback, whose only job is to give the same UX.

The split is deterministic (same text → same passages/ids) so a passage a labeler selected keeps
its id across visits as long as the chunk text is unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.passage_labels import PASSAGE_SOURCE_CHUNK_SPLIT

# A passage shorter than this (after stripping) is merged into the previous one rather than shown
# as its own checkbox — avoids splitting off "e.g." fragments, bare list bullets, or stray tokens
# that aren't a judgeable unit on their own.
_MIN_PASSAGE_CHARS = 12

# Sentence boundary: end punctuation (. ! ? and their common unicode variants) followed by
# whitespace. Kept intentionally simple — this is a display/labeling aid, not linguistic parsing;
# the durable, offset-anchored split is rde's job (the B path).
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+")


@dataclass
class SplitPassage:
    """One local sentence/line passage of a chunk, ready to present for selection."""

    passage_id: str
    text: str
    # The chunk's heading context, snapshotted onto every passage as its display grouping (the
    # section header labels the checkbox list). None when the chunk carries no heading.
    section_path: str | None
    passage_source: str = PASSAGE_SOURCE_CHUNK_SPLIT
    # Document-anchored offsets [char_start, char_end) into the parsed document, i.e.
    # ``chunk_char_start`` + the passage's offset within the chunk text. None when the chunk's own
    # document offset is unknown (legacy-chunker pages) — the in-chunk offset alone is not
    # document-anchored, so it isn't surfaced as one.
    char_start: int | None = None
    char_end: int | None = None


# One passage's text plus its [start, end) offset within the chunk text (not yet document-anchored).
_Span = tuple[str, int, int]


def _split_line_spans(line: str, base: int) -> list[_Span]:
    """Split one line into sentence spans, keeping list-item/table-row lines whole.

    A line that looks like a list item or table row is a single judgeable unit, so it isn't broken
    at internal punctuation; a prose line is split on sentence boundaries. Offsets are relative to
    the chunk text via ``base`` (the line's start offset within the chunk).
    """
    stripped = line.strip()
    if not stripped:
        return []
    lead = line.index(stripped)  # leading-whitespace length; stripped is a contiguous substring
    # List markers ("- ", "* ", "1. ", "1) ") and table rows ("| a | b |") stay whole.
    is_list = bool(re.match(r"^([-*+]\s|\d+[.)]\s)", stripped))
    is_table_row = stripped.startswith("|")
    if is_list or is_table_row:
        start = base + lead
        return [(stripped, start, start + len(stripped))]
    parts = [p.strip() for p in _SENTENCE_BOUNDARY.split(stripped) if p.strip()]
    spans: list[_Span] = []
    cursor = lead
    for p in parts:
        # Each part is a substring of the line in reading order; locate it from the running cursor.
        idx = line.find(p, cursor)
        if idx < 0:
            idx = cursor
        spans.append((p, base + idx, base + idx + len(p)))
        cursor = idx + len(p)
    return spans


def _coalesce_short_spans(spans: list[_Span]) -> list[_Span]:
    """Merge sub-``_MIN_PASSAGE_CHARS`` fragments into the previous span (or the next, if first).

    Merged spans keep the source offset range ``[previous.start, current.end)`` — contiguous within
    the line — while the display text joins the fragments with a space.
    """
    out: list[_Span] = []
    for text, start, end in spans:
        if out and len(text) < _MIN_PASSAGE_CHARS:
            pt, ps, _pe = out[-1]
            out[-1] = (f"{pt} {text}".strip(), ps, end)
        else:
            out.append((text, start, end))
    # A too-short leading fragment can't merge backward; fold it into what follows.
    if len(out) >= 2 and len(out[0][0]) < _MIN_PASSAGE_CHARS:
        t0, s0, _e0 = out[0]
        t1, _s1, e1 = out[1]
        out[1] = (f"{t0} {t1}".strip(), s0, e1)
        out = out[1:]
    return out


def split_chunk_into_passages(
    chunk_id: str,
    text: str | None,
    *,
    section_path: str | None = None,
    chunk_char_start: int | None = None,
) -> list[SplitPassage]:
    """Deterministically split a chunk's text into sentence/line passages.

    Splits on line breaks first (so list items and table rows stay whole), then on sentence
    boundaries within prose lines, coalescing fragments too short to judge on their own. Ids are
    ``{chunk_id}#s{n}`` (1-indexed, in reading order) so a selection keeps its id across visits as
    long as the text is unchanged.

    When ``chunk_char_start`` is given (the chunk's own offset into the parsed document, from the
    index), each passage is additionally anchored to document coordinates
    (``char_start = chunk_char_start + offset-within-chunk``) so the selection survives re-chunking.
    Without it, ``char_start``/``char_end`` stay ``None``. Returns ``[]`` for empty text.
    """
    if not text or not text.strip():
        return []

    # Coalesce short fragments *within* a line only. A list item or table row is a whole line of
    # its own, so per-line coalescing leaves it intact (nothing to merge it with); only the
    # sentence fragments of a prose line get merged. Cross-line merging would wrongly fold a short
    # heading line or a short table row into its neighbour.
    spans: list[_Span] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        spans.extend(_coalesce_short_spans(_split_line_spans(content, offset)))
        offset += len(line)

    passages: list[SplitPassage] = []
    for n, (part_text, start, end) in enumerate(spans, start=1):
        doc_start = None if chunk_char_start is None else chunk_char_start + start
        doc_end = None if chunk_char_start is None else chunk_char_start + end
        passages.append(
            SplitPassage(
                passage_id=f"{chunk_id}#s{n}",
                text=part_text,
                section_path=section_path or None,
                char_start=doc_start,
                char_end=doc_end,
            )
        )
    return passages
