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


def _split_line(line: str) -> list[str]:
    """Split one line into sentences, keeping list-item/table-row lines whole.

    A line that looks like a list item or table row is a single judgeable unit, so it isn't broken
    at internal punctuation; a prose line is split on sentence boundaries.
    """
    stripped = line.strip()
    if not stripped:
        return []
    # List markers ("- ", "* ", "1. ", "1) ") and table rows ("| a | b |") stay whole.
    is_list = bool(re.match(r"^([-*+]\s|\d+[.)]\s)", stripped))
    is_table_row = stripped.startswith("|")
    if is_list or is_table_row:
        return [stripped]
    parts = _SENTENCE_BOUNDARY.split(stripped)
    return [p.strip() for p in parts if p.strip()]


def _coalesce_short(parts: list[str]) -> list[str]:
    """Merge sub-``_MIN_PASSAGE_CHARS`` fragments into the previous part (or the next, if first)."""
    out: list[str] = []
    for part in parts:
        if out and len(part) < _MIN_PASSAGE_CHARS:
            out[-1] = f"{out[-1]} {part}".strip()
        else:
            out.append(part)
    # A too-short leading fragment can't merge backward; fold it into what follows.
    if len(out) >= 2 and len(out[0]) < _MIN_PASSAGE_CHARS:
        out[1] = f"{out[0]} {out[1]}".strip()
        out = out[1:]
    return out


def split_chunk_into_passages(
    chunk_id: str, text: str | None, *, section_path: str | None = None
) -> list[SplitPassage]:
    """Deterministically split a chunk's text into sentence/line passages.

    Splits on line breaks first (so list items and table rows stay whole), then on sentence
    boundaries within prose lines, coalescing fragments too short to judge on their own. Ids are
    ``{chunk_id}#s{n}`` (1-indexed, in reading order) so a selection keeps its id across visits as
    long as the text is unchanged. Returns ``[]`` for empty text.
    """
    if not text or not text.strip():
        return []

    # Coalesce short fragments *within* a line only. A list item or table row is a whole line of
    # its own, so per-line coalescing leaves it intact (nothing to merge it with); only the
    # sentence fragments of a prose line get merged. Cross-line merging would wrongly fold a short
    # heading line or a short table row into its neighbour.
    parts: list[str] = []
    for line in text.splitlines():
        parts.extend(_coalesce_short(_split_line(line)))

    passages: list[SplitPassage] = []
    for n, part in enumerate(parts, start=1):
        passages.append(
            SplitPassage(
                passage_id=f"{chunk_id}#s{n}",
                text=part,
                section_path=section_path or None,
            )
        )
    return passages
