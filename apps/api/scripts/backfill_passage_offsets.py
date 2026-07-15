"""Backfill document-anchored char offsets onto existing passage selections.

Passage labels saved before their chunk carried ``chunk_char_start`` (legacy-chunker pages, or
rows written before offset support) have ``char_start``/``char_end`` NULL. Once the index doc for
their chunk gains ``chunk_char_start`` — *without* the chunk being re-chunked — we can recompute
those offsets: re-run the same deterministic split and add the chunk's document offset.

The load-bearing safety guard is ``text_preview``: every row snapshots the passage's original text,
so we only write an offset when the freshly re-split passage's text still matches. If the chunk was
re-chunked (text drifted, or the chunk id no longer exists in the index), the row is left untouched
and counted as skipped — its offsets can't be trusted, so we don't guess.

This only ever fills NULL offsets on ``chunk_split`` rows; it never overwrites a non-NULL offset and
never touches ``relevant`` or any other column. It is idempotent and safe to re-run.

Usage:
    poetry run python scripts/backfill_passage_offsets.py [--dry-run] [--project-id UUID]
                                                          [--batch-size N]

``--dry-run`` reports what would change without writing. Run this *before* enabling a re-chunk
(e.g. DI page processing) so labels get anchored while their chunk still exists.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import defaultdict
from pathlib import Path
from uuid import UUID

# Ensure the API root (apps/api) is importable regardless of invocation cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import async_session  # noqa: E402
from app.index_providers.registry import build_index_provider  # noqa: E402
from app.models.index_providers import IndexProvider  # noqa: E402
from app.models.passage_labels import PASSAGE_SOURCE_CHUNK_SPLIT, PassageRelevanceLabel  # noqa: E402
from app.routers.chunk_labels._helpers import (  # noqa: E402
    INDEX_CHAR_START_FIELDS,
    INDEX_HEADING_FIELDS,
    INDEX_TEXT_FIELDS,
    _first_int_field,
    _first_str_field,
)
from app.services.passage_split import split_chunk_into_passages  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_passage_offsets")


class Stats:
    """Running tallies for the run summary (per-outcome so the report is legible)."""

    def __init__(self) -> None:
        self.anchored = 0            # rows given fresh offsets
        self.no_offset = 0           # chunk still lacks chunk_char_start in the index
        self.chunk_missing = 0       # chunk id no longer in the index (likely re-chunked)
        self.no_split_match = 0      # passage_id not produced by the current split (text changed)
        self.drifted = 0             # split matched but its text != the row's snapshot
        self.chunks_seen = 0
        self.chunks_anchored = 0


async def _provider_for_project(session, project_id: UUID):
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


def _batched(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def _backfill_project(
    session, project_id: UUID, rows: list[PassageRelevanceLabel], *, batch_size: int, dry_run: bool
) -> Stats:
    stats = Stats()
    provider = await _provider_for_project(session, project_id)
    if provider is None:
        logger.info("  project %s: no index provider — skipping %d rows", project_id, len(rows))
        stats.no_offset += len(rows)  # can't anchor without an index; count as unresolved
        return stats

    # Group the project's null-offset rows by chunk so we fetch each chunk once and re-split once.
    by_chunk: dict[str, list[PassageRelevanceLabel]] = defaultdict(list)
    for r in rows:
        by_chunk[r.chunk_id].append(r)
    chunk_ids = list(by_chunk.keys())
    stats.chunks_seen = len(chunk_ids)

    docs: dict[str, dict] = {}
    try:
        for batch in _batched(chunk_ids, batch_size):
            fetched = await provider.fetch_documents_by_key(batch)
            for cid, fields in (fetched or {}).items():
                if isinstance(fields, dict):
                    docs[cid] = fields
    finally:
        await provider.aclose()

    for chunk_id, chunk_rows in by_chunk.items():
        fields = docs.get(chunk_id)
        if fields is None:
            stats.chunk_missing += len(chunk_rows)  # re-chunked or deleted — can't recover here
            continue
        chunk_char_start = _first_int_field(fields, INDEX_CHAR_START_FIELDS)
        if chunk_char_start is None:
            stats.no_offset += len(chunk_rows)  # index doc still carries no offset
            continue
        text = _first_str_field(fields, INDEX_TEXT_FIELDS)
        heading = _first_str_field(fields, INDEX_HEADING_FIELDS)
        split = split_chunk_into_passages(
            chunk_id, text, section_path=heading, chunk_char_start=chunk_char_start
        )
        by_pid = {p.passage_id: p for p in split}

        anchored_here = 0
        for r in chunk_rows:
            p = by_pid.get(r.passage_id)
            if p is None:
                stats.no_split_match += 1
                continue
            # Guard: only trust the offset if the passage text still matches the row's snapshot.
            if r.text_preview is not None and p.text != r.text_preview:
                stats.drifted += 1
                continue
            if p.char_start is None:  # shouldn't happen (chunk_char_start is set) but stay defensive
                stats.no_offset += 1
                continue
            if not dry_run:
                r.char_start = p.char_start
                r.char_end = p.char_end
            stats.anchored += 1
            anchored_here += 1
        if anchored_here:
            stats.chunks_anchored += 1

    if not dry_run:
        await session.commit()
    return stats


async def _run(project_id: UUID | None, batch_size: int, dry_run: bool) -> Stats:
    total = Stats()
    async with async_session() as session:
        q = select(PassageRelevanceLabel).where(
            PassageRelevanceLabel.char_start.is_(None),
            PassageRelevanceLabel.passage_source == PASSAGE_SOURCE_CHUNK_SPLIT,
        )
        if project_id is not None:
            q = q.where(PassageRelevanceLabel.project_id == project_id)
        rows = (await session.execute(q)).scalars().all()

        by_project: dict[UUID, list[PassageRelevanceLabel]] = defaultdict(list)
        for r in rows:
            by_project[r.project_id].append(r)

        logger.info(
            "%d null-offset chunk_split rows across %d project(s)%s",
            len(rows),
            len(by_project),
            " [DRY RUN]" if dry_run else "",
        )
        for pid, prows in by_project.items():
            s = await _backfill_project(
                session, pid, prows, batch_size=batch_size, dry_run=dry_run
            )
            logger.info(
                "  project %s: anchored=%d, chunks=%d/%d, no_offset=%d, chunk_missing=%d, "
                "no_match=%d, drifted=%d",
                pid,
                s.anchored,
                s.chunks_anchored,
                s.chunks_seen,
                s.no_offset,
                s.chunk_missing,
                s.no_split_match,
                s.drifted,
            )
            for attr in vars(s):
                setattr(total, attr, getattr(total, attr) + getattr(s, attr))
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
    parser.add_argument("--project-id", type=UUID, default=None, help="Limit to one project.")
    parser.add_argument(
        "--batch-size", type=int, default=50, help="Index-fetch batch size (default 50)."
    )
    args = parser.parse_args()

    total = asyncio.run(_run(args.project_id, args.batch_size, args.dry_run))
    logger.info(
        "\nDone%s: anchored=%d rows, skipped no_offset=%d, chunk_missing=%d, no_match=%d, "
        "drifted=%d",
        " (dry run — nothing written)" if args.dry_run else "",
        total.anchored,
        total.no_offset,
        total.chunk_missing,
        total.no_split_match,
        total.drifted,
    )


if __name__ == "__main__":
    main()
