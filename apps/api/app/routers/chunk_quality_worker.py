"""Background worker for a chunk/metadata quality run.

Mirrors ``source_registry_worker``: spawned via ``asyncio.create_task`` from the
router, owns its DB sessions through the session factory, and drives a
``ChunkQualityRun`` row through pending → running → completed/failed.

A provider that can't sample its corpus (``NotImplementedError``) is not a
failure — the run completes with a single "unavailable" finding so the UI can
explain why there's nothing to show.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.index_providers.chunk_quality import run_chunk_quality
from app.index_providers.registry import build_index_provider
from app.models.chunk_quality import ChunkQualityRun
from app.models.index_providers import IndexProvider

logger = logging.getLogger(__name__)


def _unavailable_results(message: str) -> dict:
    return {
        "summary": {"score": 0, "findings_total": 1, "critical": 1, "warn": 0, "info": 0},
        "score": 0,
        "fields": {},
        "families": {},
        "findings": [{
            "family": "metadata", "severity": "critical",
            "title": "Quality analysis unavailable",
            "message": message, "count": 0, "examples": [],
        }],
    }


async def run_chunk_quality_analysis(
    *,
    run_id: UUID,
    project_id: UUID,
    provider_id: UUID,
    sample_size: int,
    db_factory,
) -> None:
    provider_obj = None
    try:
        async with db_factory() as db:
            run = (
                await db.execute(select(ChunkQualityRun).where(ChunkQualityRun.id == run_id))
            ).scalar_one_or_none()
            if run is None:
                raise ValueError(f"Chunk quality run {run_id} not found")
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)

            provider_row = (
                await db.execute(
                    select(IndexProvider).where(
                        IndexProvider.id == provider_id, IndexProvider.project_id == project_id
                    )
                )
            ).scalar_one_or_none()
            if provider_row is None:
                raise ValueError("Index provider not found")
            await db.commit()

            provider_obj = build_index_provider(provider_row)

            async def save_progress(processed: int) -> None:
                async with db_factory() as progress_db:
                    progress_run = (
                        await progress_db.execute(
                            select(ChunkQualityRun).where(ChunkQualityRun.id == run_id)
                        )
                    ).scalar_one_or_none()
                    if progress_run is not None:
                        progress_run.processed = processed
                        await progress_db.commit()

            try:
                report = await run_chunk_quality(
                    provider_obj, sample_size=sample_size, progress_cb=save_progress
                )
                results = report.to_dict()
                total_docs = report.total_docs
                processed = report.sample_size
            except NotImplementedError as exc:
                results = _unavailable_results(
                    f"This index provider does not support corpus sampling ({exc})."
                )
                total_docs = 0
                processed = 0

            async with db_factory() as final_db:
                final_run = (
                    await final_db.execute(
                        select(ChunkQualityRun).where(ChunkQualityRun.id == run_id)
                    )
                ).scalar_one_or_none()
                if final_run is not None:
                    final_run.results = results
                    final_run.total_docs = total_docs
                    final_run.processed = processed
                    final_run.status = "completed"
                    final_run.completed_at = datetime.now(timezone.utc)
                    await final_db.commit()
    except Exception as e:
        logger.exception("Chunk quality run %s failed", run_id)
        try:
            async with db_factory() as db:
                run = (
                    await db.execute(select(ChunkQualityRun).where(ChunkQualityRun.id == run_id))
                ).scalar_one_or_none()
                if run is not None:
                    run.status = "failed"
                    run.error = str(e)
                    run.completed_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            logger.exception("Failed to record chunk quality run error for %s", run_id)
    finally:
        if provider_obj is not None:
            try:
                await provider_obj.aclose()
            except Exception:
                logger.debug("Provider aclose failed", exc_info=True)
