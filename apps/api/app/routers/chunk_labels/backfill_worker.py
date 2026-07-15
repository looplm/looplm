"""Background worker for a passage document-offset backfill run.

Mirrors ``chunk_quality_worker``: spawned via ``asyncio.create_task`` from the router, owns its DB
sessions through the session factory, and drives a ``PassageOffsetBackfillRun`` row through
pending → running → completed/failed. The actual anchoring is the shared
``backfill_project_offsets`` service (also used by the CLI script).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.models.passage_offset_backfill import PassageOffsetBackfillRun
from app.services.passage_offset_backfill import backfill_project_offsets

logger = logging.getLogger(__name__)


async def run_passage_offset_backfill(*, run_id: UUID, project_id: UUID, db_factory) -> None:
    try:
        async with db_factory() as db:
            run = (
                await db.execute(
                    select(PassageOffsetBackfillRun).where(
                        PassageOffsetBackfillRun.id == run_id
                    )
                )
            ).scalar_one_or_none()
            if run is None:
                raise ValueError(f"Passage offset backfill run {run_id} not found")
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            await db.commit()

        async def save_progress(processed: int, total: int) -> None:
            async with db_factory() as progress_db:
                progress_run = (
                    await progress_db.execute(
                        select(PassageOffsetBackfillRun).where(
                            PassageOffsetBackfillRun.id == run_id
                        )
                    )
                ).scalar_one_or_none()
                if progress_run is not None and progress_run.status == "running":
                    progress_run.processed_chunks = processed
                    progress_run.total_chunks = total
                    await progress_db.commit()

        async with db_factory() as work_db:
            outcome = await backfill_project_offsets(
                work_db, project_id, progress_cb=save_progress
            )
            await work_db.commit()

        async with db_factory() as final_db:
            final_run = (
                await final_db.execute(
                    select(PassageOffsetBackfillRun).where(
                        PassageOffsetBackfillRun.id == run_id
                    )
                )
            ).scalar_one_or_none()
            if final_run is not None:
                final_run.status = "completed"
                final_run.total_chunks = outcome.chunks_seen
                final_run.processed_chunks = outcome.chunks_seen
                final_run.anchored = outcome.anchored
                final_run.no_offset = outcome.no_offset
                final_run.chunk_missing = outcome.chunk_missing
                final_run.no_split_match = outcome.no_split_match
                final_run.drifted = outcome.drifted
                final_run.completed_at = datetime.now(timezone.utc)
                await final_db.commit()
    except Exception as e:
        logger.exception("Passage offset backfill run %s failed", run_id)
        try:
            async with db_factory() as db:
                run = (
                    await db.execute(
                        select(PassageOffsetBackfillRun).where(
                            PassageOffsetBackfillRun.id == run_id
                        )
                    )
                ).scalar_one_or_none()
                if run is not None:
                    run.status = "failed"
                    run.error = str(e)
                    run.completed_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            logger.exception("Failed to record passage offset backfill error for %s", run_id)
