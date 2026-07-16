"""Recompute document-anchored char offsets on existing passage selections.

Shared core behind both the CLI script (``scripts/backfill_passage_offsets.py``) and the web-UI
background job (``routers/chunk_labels/backfill_worker.py``). Passage labels saved before their
chunk carried ``chunk_char_start`` have NULL offsets; once the index doc for a chunk gains the
offset — *without* the chunk being re-chunked — we re-run the same deterministic split and add the
chunk's document offset.

The load-bearing safety guard is ``text_preview``: every row snapshots the passage's original text,
so an offset is written only when the freshly re-split passage's text still matches. If the chunk
was re-chunked (text drifted, or the id no longer exists in the index) the row is left untouched and
counted as skipped — its offset can't be trusted, so we never guess.

Only NULL offsets on ``chunk_split`` rows are ever touched; a non-NULL offset is never overwritten
and ``relevant`` is never changed. Idempotent. The caller owns the transaction (commit).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.index_providers.registry import build_index_provider
from app.models.index_providers import IndexProvider
from app.models.passage_labels import PASSAGE_SOURCE_CHUNK_SPLIT, PassageRelevanceLabel
from app.services.index_fields import (
    INDEX_CHAR_START_FIELDS,
    INDEX_HEADING_FIELDS,
    INDEX_TEXT_FIELDS,
    first_int_field,
    first_str_field,
)
from app.services.passage_split import match_passage_anchors, split_chunk_into_passages

logger = logging.getLogger(__name__)

# Emit a progress update every this many chunks so the UI's bar advances without a commit per chunk.
_PROGRESS_EVERY = 20

ProgressCb = Callable[[int, int], Awaitable[None]]


@dataclass
class BackfillOutcome:
    """Per-outcome tallies for one project's backfill, so the report explains every skip."""

    anchored: int = 0            # rows given fresh offsets
    no_offset: int = 0           # chunk still lacks chunk_char_start in the index
    chunk_missing: int = 0       # chunk id no longer in the index (likely re-chunked)
    no_split_match: int = 0      # passage_id not produced by the current split (text changed)
    drifted: int = 0             # split matched but its text != the row's snapshot
    chunks_seen: int = 0
    chunks_anchored: int = 0


def _batched(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def _provider_for_project(session: AsyncSession, project_id: UUID):
    """The project's index provider (earliest-created), mirroring the labeling read path."""
    row = (
        await session.execute(
            select(IndexProvider)
            .where(IndexProvider.project_id == project_id)
            .order_by(IndexProvider.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return build_index_provider(row) if row is not None else None


async def backfill_project_offsets(
    session: AsyncSession,
    project_id: UUID,
    *,
    dry_run: bool = False,
    batch_size: int = 50,
    progress_cb: ProgressCb | None = None,
) -> BackfillOutcome:
    """Anchor NULL-offset ``chunk_split`` passage labels for one project. Caller commits.

    Fetches each chunk's live index doc once (batched), re-splits, and fills ``char_start`` /
    ``char_end`` for rows whose passage text still matches. ``dry_run`` computes the same tallies
    without mutating. ``progress_cb(processed_chunks, total_chunks)`` is called periodically.
    """
    outcome = BackfillOutcome()

    rows = (
        await session.execute(
            select(PassageRelevanceLabel).where(
                PassageRelevanceLabel.project_id == project_id,
                PassageRelevanceLabel.char_start.is_(None),
                PassageRelevanceLabel.passage_source == PASSAGE_SOURCE_CHUNK_SPLIT,
            )
        )
    ).scalars().all()
    if not rows:
        if progress_cb is not None:
            await progress_cb(0, 0)
        return outcome

    # Group by chunk so each chunk is fetched once and re-split once; all rows for a passage_id
    # (across test cases / annotators) get the same offset since it's purely a function of the text.
    by_chunk: dict[str, list[PassageRelevanceLabel]] = defaultdict(list)
    for r in rows:
        by_chunk[r.chunk_id].append(r)
    chunk_ids = list(by_chunk.keys())
    outcome.chunks_seen = len(chunk_ids)

    provider = await _provider_for_project(session, project_id)
    if provider is None:
        # No index to anchor against — nothing recoverable this run.
        outcome.no_offset = len(rows)
        if progress_cb is not None:
            await progress_cb(len(chunk_ids), len(chunk_ids))
        return outcome

    docs: dict[str, dict] = {}
    try:
        for batch in _batched(chunk_ids, batch_size):
            fetched = await provider.fetch_documents_by_key(batch)
            for cid, fields in (fetched or {}).items():
                if isinstance(fields, dict):
                    docs[cid] = fields
    finally:
        await provider.aclose()

    processed = 0
    if progress_cb is not None:
        await progress_cb(0, len(chunk_ids))

    for chunk_id, chunk_rows in by_chunk.items():
        fields = docs.get(chunk_id)
        if fields is None:
            outcome.chunk_missing += len(chunk_rows)  # re-chunked or deleted — can't recover here
        else:
            chunk_char_start = first_int_field(fields, INDEX_CHAR_START_FIELDS)
            if chunk_char_start is None:
                outcome.no_offset += len(chunk_rows)  # index doc still carries no offset
            else:
                text = first_str_field(fields, INDEX_TEXT_FIELDS)
                heading = first_str_field(fields, INDEX_HEADING_FIELDS)
                fresh = split_chunk_into_passages(
                    chunk_id, text, section_path=heading, chunk_char_start=chunk_char_start
                )
                # These rows have no offset yet, so match them to the fresh split by text (then by
                # positional id) rather than the id alone — recovers labels the splitter renumbered.
                matches = match_passage_anchors(
                    [(p.passage_id, p.char_start, p.char_end, p.text) for p in fresh],
                    [(r.passage_id, r.char_start, r.char_end, r.text_preview) for r in chunk_rows],
                )
                fresh_for_row = {si: fresh[fi] for fi, si in matches.items()}
                anchored_here = 0
                for ri, r in enumerate(chunk_rows):
                    p = fresh_for_row.get(ri)
                    if p is None:
                        outcome.no_split_match += 1
                    elif r.text_preview is not None and p.text != r.text_preview:
                        outcome.drifted += 1  # text changed — offset can't be trusted
                    elif p.char_start is None:
                        outcome.no_offset += 1  # defensive; chunk_char_start was set, shouldn't hit
                    else:
                        if not dry_run:
                            r.char_start = p.char_start
                            r.char_end = p.char_end
                        outcome.anchored += 1
                        anchored_here += 1
                if anchored_here:
                    outcome.chunks_anchored += 1

        processed += 1
        if progress_cb is not None and processed % _PROGRESS_EVERY == 0:
            await progress_cb(processed, len(chunk_ids))

    if progress_cb is not None:
        await progress_cb(len(chunk_ids), len(chunk_ids))
    return outcome
