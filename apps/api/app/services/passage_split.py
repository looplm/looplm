"""Split a pooled chunk's own text into sentence-level passages — the *A* passage source.

Passage labeling grades finer units than a chunk: a sentence, list item, or table row a labeler
can "uncheck" when it doesn't help answer the query. The preferred source (*B*) is stable,
offset-anchored sentence sub-passages derived by the rde indexer, whose ids survive re-chunking.
When those aren't available (no rde-derived passages for the page, or rde unreachable), we fall
back here: split the pooled chunk's ``chunk_text`` locally into sentence/line passages under its
heading context. These ids are chunk-derived (``{chunk_id}#s{n}``) so they orphan when the index
is re-chunked — acceptable for the fallback, whose only job is to give the same UX.

Chunk text extracted from PDFs is typically **hard-wrapped** mid-sentence at a fixed column width,
so a physical line break is not a sentence boundary. We therefore *reflow* consecutive prose lines
back into a paragraph before sentence-splitting; only genuinely structural lines (blank line, list
item, table row, heading) act as boundaries. Without this a single wrapped sentence would surface
as several stray checkboxes.

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

# A list marker ("- ", "* ", "+ ", "1. ", "1) ") or ATX heading ("# " … "###### ") at line start.
# These lines — plus table rows ("| a | b |") — are whole judgeable units, never joined into a
# reflowed paragraph and never broken at internal punctuation.
_LIST_MARKER = re.compile(r"^([-*+]\s|\d+[.)]\s)")
_HEADING = re.compile(r"^#{1,6}\s")

# A key/value or definition line ("Name: John", "partition_value: bundesnetzagentur"): a short
# label, then ": ", then a value. Line-oriented data (form fields, metadata rows) should stay one
# judgeable unit per line rather than being reflowed into one un-splittable block, so such a line
# is a whole-line unit too. The label is capped and the colon must be followed by whitespace, so
# URLs ("http://…"), clock times ("12:30"), and code stay out. Trade-off: a wrapped prose line
# whose first physical line ends a short phrase with a colon ("Er erklärte Folgendes: …") is also
# treated as standalone rather than reflowed — acceptable for a display/labeling aid.
_KEY_VALUE = re.compile(r"^[^\s:][^:]{0,39}:\s+\S")

# Every newline char, replaced 1:1 with a space when reflowing so the reflowed paragraph is
# length-preserving — offsets into it map straight back to the original chunk text.
_NEWLINE_CHAR = re.compile(r"[\r\n]")


def _is_whole_line_unit(stripped: str) -> bool:
    """True for a line that is its own passage — a list item, table row, or heading.

    Such a line is neither joined into a reflowed prose paragraph nor split at internal punctuation.
    """
    return (
        bool(_LIST_MARKER.match(stripped))
        or stripped.startswith("|")
        or bool(_HEADING.match(stripped))
        or bool(_KEY_VALUE.match(stripped))
    )


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
    # List markers, table rows, and headings stay whole (see ``_is_whole_line_unit``).
    if _is_whole_line_unit(stripped):
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

    Reflows consecutive prose lines into a paragraph (undoing PDF hard-wrapping), then splits each
    paragraph on sentence boundaries, coalescing fragments too short to judge on their own. Only
    structural lines act as boundaries: a blank line separates paragraphs, and a list item / table
    row / heading is its own whole unit (never joined, never split at internal punctuation). Ids are
    ``{chunk_id}#s{n}`` (1-indexed, in reading order) so a selection keeps its id across visits as
    long as the text is unchanged.

    When ``chunk_char_start`` is given (the chunk's own offset into the parsed document, from the
    index), each passage is additionally anchored to document coordinates
    (``char_start = chunk_char_start + offset-within-chunk``) so the selection survives re-chunking.
    Without it, ``char_start``/``char_end`` stay ``None``. Returns ``[]`` for empty text.
    """
    if not text or not text.strip():
        return []

    spans: list[_Span] = []
    # A prose paragraph in progress: [para_start, para_end) into the chunk text, spanning one or
    # more hard-wrapped lines. Flushed (reflowed and sentence-split) at the next structural line,
    # blank line, or end of text.
    para_start: int | None = None
    para_end = 0

    def _flush_paragraph() -> None:
        nonlocal para_start
        if para_start is None:
            return
        # The slice covers the prose lines plus the newline chars between them; replacing each
        # newline with a space is length-preserving, so sentence offsets map 1:1 back to the chunk.
        reflowed = _NEWLINE_CHAR.sub(" ", text[para_start:para_end])
        spans.extend(_coalesce_short_spans(_split_line_spans(reflowed, para_start)))
        para_start = None

    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        start = offset
        offset += len(line)
        stripped = content.strip()
        if not stripped:  # blank line — paragraph boundary, nothing to emit
            _flush_paragraph()
            continue
        if _is_whole_line_unit(stripped):  # list item / table row / heading — its own unit
            _flush_paragraph()
            spans.extend(_coalesce_short_spans(_split_line_spans(content, start)))
            continue
        # Prose line — accumulate into the current paragraph so wrapped sentences reflow whole.
        if para_start is None:
            para_start = start
        para_end = start + len(content)
    _flush_paragraph()

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


# (passage_id, char_start, char_end, text) — the minimal fields needed to re-match a passage.
PassageAnchor = tuple[str, int | None, int | None, str | None]


def match_passage_anchors(
    fresh: list[PassageAnchor], stored: list[PassageAnchor]
) -> dict[int, int]:
    """Re-match stored passage labels to freshly-split passages, durably across splitter changes.

    A stored label is keyed on disk by its positional ``{chunk_id}#s{n}`` id, which is *not* stable
    when the splitter changes (reflow, heading/key-value handling): the same chunk text can renumber
    every passage, so matching by id alone silently attaches a labeler's selection to the wrong
    sentence — or loses it. Instead we re-match by **document offsets** and **text**, using the
    positional id only as a last resort.

    Matching runs in priority tiers; each tier claims stored rows the earlier tiers left unmatched,
    and every stored row is assigned to at most one fresh passage:

      1. exact ``[char_start, char_end)`` equality (both anchored) — the steady-state case, where a
         label re-resolves to the identical passage on the next visit;
      2. offset overlap (both anchored) — a boundary shifted by a re-split still re-anchors;
      3. exact text equality — recovers rows with no offsets (legacy, pre-offset pages);
      4. positional ``passage_id`` equality — last-resort legacy behavior.

    Returns ``{fresh_index: stored_index}`` (absent fresh indices had no match).
    """
    result: dict[int, int] = {}
    claimed: set[int] = set()

    def _assign(pred) -> None:
        for fi, f in enumerate(fresh):
            if fi in result:
                continue
            for si, s in enumerate(stored):
                if si in claimed:
                    continue
                if pred(f, s):
                    result[fi] = si
                    claimed.add(si)
                    break

    def _both_anchored(f: PassageAnchor, s: PassageAnchor) -> bool:
        return f[1] is not None and f[2] is not None and s[1] is not None and s[2] is not None

    _assign(lambda f, s: _both_anchored(f, s) and f[1] == s[1] and f[2] == s[2])
    _assign(lambda f, s: _both_anchored(f, s) and max(f[1], s[1]) < min(f[2], s[2]))
    _assign(lambda f, s: bool(f[3]) and f[3] == s[3])
    _assign(lambda f, s: f[0] == s[0])
    return result
