"""Background worker for a wanted-status gap run.

Mirrors ``rag_coverage_worker``: spawned via ``asyncio.create_task`` from the
router, owns its DB sessions through the session factory, and drives a
``SourceGapRun`` row through pending → running → completed/failed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.index_providers.registry import build_index_provider
from app.index_providers.source_gaps import ExpectationInput, run_gap_analysis
from app.models.index_providers import IndexProvider
from app.models.source_registry import SourceExpectation, SourceGapRun

logger = logging.getLogger(__name__)


async def run_source_gap_analysis(
    *,
    run_id: UUID,
    project_id: UUID,
    provider_id: UUID,
    db_factory,
) -> None:
    provider_obj = None
    try:
        async with db_factory() as db:
            run = (
                await db.execute(select(SourceGapRun).where(SourceGapRun.id == run_id))
            ).scalar_one_or_none()
            if run is None:
                raise ValueError(f"Source gap run {run_id} not found")
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

            expectation_rows = list(
                (
                    await db.execute(
                        select(SourceExpectation).where(
                            SourceExpectation.project_id == project_id,
                            SourceExpectation.provider_id == provider_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            expectations = [
                ExpectationInput(
                    id=str(e.id),
                    name=e.name,
                    html_url=e.html_url,
                    pdf_url=e.pdf_url,
                    adapter_tag=e.adapter_tag,
                    ack_note=e.ack_note,
                )
                for e in expectation_rows
            ]
            run.total = len(expectations)
            await db.commit()

            provider_obj = build_index_provider(provider_row)

            async def save_progress(processed: int) -> None:
                async with db_factory() as progress_db:
                    progress_run = (
                        await progress_db.execute(
                            select(SourceGapRun).where(SourceGapRun.id == run_id)
                        )
                    ).scalar_one_or_none()
                    if progress_run is not None:
                        progress_run.processed = processed
                        await progress_db.commit()

            report = await run_gap_analysis(
                provider_obj, expectations, progress_cb=save_progress
            )

            async with db_factory() as final_db:
                final_run = (
                    await final_db.execute(
                        select(SourceGapRun).where(SourceGapRun.id == run_id)
                    )
                ).scalar_one_or_none()
                if final_run is not None:
                    final_run.results = report.to_dict()
                    final_run.processed = len(expectations)
                    final_run.status = "completed"
                    final_run.completed_at = datetime.now(timezone.utc)
                    await final_db.commit()
    except Exception as e:
        logger.exception("Source gap run %s failed", run_id)
        try:
            async with db_factory() as db:
                run = (
                    await db.execute(select(SourceGapRun).where(SourceGapRun.id == run_id))
                ).scalar_one_or_none()
                if run is not None:
                    run.status = "failed"
                    run.error = str(e)
                    run.completed_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            logger.exception("Failed to record source gap run error for %s", run_id)
    finally:
        if provider_obj is not None:
            try:
                await provider_obj.aclose()
            except Exception:
                logger.debug("Provider aclose failed", exc_info=True)
