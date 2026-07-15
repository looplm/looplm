"""Backfill document-anchored char offsets onto existing passage selections (CLI).

Thin wrapper over ``app.services.passage_offset_backfill`` — the same core the web-UI background
job uses. Passage labels saved before their chunk carried ``chunk_char_start`` have NULL offsets;
once the index doc for a chunk gains the offset (without a re-chunk), this recomputes them by
re-running the deterministic split and adding the chunk's document offset, guarded by the stored
``text_preview`` snapshot so only unchanged passages are anchored.

Only fills NULL offsets on ``chunk_split`` rows; never overwrites, never touches relevance.
Idempotent. Run it *before* enabling a re-chunk (e.g. DI page processing) so labels get anchored
while their chunk still exists.

Usage:
    poetry run python scripts/backfill_passage_offsets.py [--dry-run] [--project-id UUID]
                                                          [--batch-size N]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from uuid import UUID

# Ensure the API root (apps/api) is importable regardless of invocation cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import async_session  # noqa: E402
from app.models.passage_labels import PASSAGE_SOURCE_CHUNK_SPLIT, PassageRelevanceLabel  # noqa: E402
from app.services.passage_offset_backfill import (  # noqa: E402
    BackfillOutcome,
    backfill_project_offsets,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_passage_offsets")


async def _run(project_id: UUID | None, batch_size: int, dry_run: bool) -> BackfillOutcome:
    total = BackfillOutcome()
    async with async_session() as session:
        # Which projects have NULL-offset chunk_split rows to work on.
        q = select(PassageRelevanceLabel.project_id).where(
            PassageRelevanceLabel.char_start.is_(None),
            PassageRelevanceLabel.passage_source == PASSAGE_SOURCE_CHUNK_SPLIT,
        )
        if project_id is not None:
            q = q.where(PassageRelevanceLabel.project_id == project_id)
        project_ids = sorted({pid for pid in (await session.execute(q.distinct())).scalars().all()})

        logger.info(
            "%d project(s) with null-offset passage labels%s",
            len(project_ids),
            " [DRY RUN]" if dry_run else "",
        )
        for pid in project_ids:
            s = await backfill_project_offsets(
                session, pid, dry_run=dry_run, batch_size=batch_size
            )
            if not dry_run:
                await session.commit()
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
