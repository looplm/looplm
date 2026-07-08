"""Background worker for a source-completeness scan.

Mirrors ``source_registry_worker``: spawned via ``asyncio.create_task`` from the
router, owns its DB sessions through the session factory, and drives a
``SourceScanRun`` through pending → running → completed/failed. Per-source
verdicts are upserted into ``SourceScanResult`` as they land (concurrent scans
each open their own short-lived session, so there is no shared-session hazard).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.config import settings
from app.index_providers.registry import build_index_provider
from app.models.index_providers import IndexProvider
from app.models.source_registry import SourceExpectation, SourceScanResult, SourceScanRun
from app.services.source_chunks import SourceChunkInput
from app.services.source_scan import ScanItemOutcome, scan_sources

logger = logging.getLogger(__name__)


async def _load_source_ids(db, project_id: UUID, provider_id: UUID, scope: str) -> list[UUID]:
    """Expectation ids to scan: all, or (scope='dlq') only those that errored."""
    stmt = select(SourceExpectation.id).where(
        SourceExpectation.project_id == project_id,
        SourceExpectation.provider_id == provider_id,
    )
    if scope == "dlq":
        stmt = stmt.join(
            SourceScanResult, SourceScanResult.expectation_id == SourceExpectation.id
        ).where(SourceScanResult.execution_status == "error")
    return list((await db.execute(stmt)).scalars().all())


async def _upsert_result(
    db_factory, project_id: UUID, provider_id: UUID, outcome: ScanItemOutcome
) -> None:
    """Persist one source's verdict, replacing any prior row for that source."""
    async with db_factory() as db:
        row = (
            await db.execute(
                select(SourceScanResult).where(
                    SourceScanResult.project_id == project_id,
                    SourceScanResult.provider_id == provider_id,
                    SourceScanResult.expectation_id == UUID(outcome.expectation_id),
                )
            )
        ).scalar_one_or_none()
        v = outcome.verdict
        values = {
            "resolution": v.resolution if v else "none",
            "resolved": bool(v and v.resolved),
            "kind": v.kind if v else None,
            "matched_url": (v.matched_url if v else None),
            "matched_title": (v.matched_title[:512] if v and v.matched_title else None),
            "chunk_count": v.chunk_count if v else 0,
            "missing_chunk_count": v.missing_chunk_count if v else 0,
            "ordinal_checked": bool(v and v.ordinal_checked),
            "execution_status": outcome.execution_status,
            "error": outcome.error,
            "scanned_at": datetime.now(timezone.utc),
        }
        if row is None:
            db.add(
                SourceScanResult(
                    project_id=project_id,
                    provider_id=provider_id,
                    expectation_id=UUID(outcome.expectation_id),
                    **values,
                )
            )
        else:
            for k, val in values.items():
                setattr(row, k, val)
        await db.commit()


async def run_source_scan(
    *,
    scan_id: UUID,
    project_id: UUID,
    provider_id: UUID,
    scope: str,
    db_factory,
) -> None:
    provider_obj = None
    try:
        async with db_factory() as db:
            run = (
                await db.execute(select(SourceScanRun).where(SourceScanRun.id == scan_id))
            ).scalar_one_or_none()
            if run is None:
                raise ValueError(f"Source scan run {scan_id} not found")
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

            source_ids = await _load_source_ids(db, project_id, provider_id, scope)
            expectation_rows = list(
                (
                    await db.execute(
                        select(SourceExpectation).where(SourceExpectation.id.in_(source_ids))
                    )
                )
                .scalars()
                .all()
            ) if source_ids else []
            sources = [
                SourceChunkInput(
                    id=str(e.id),
                    name=e.name,
                    html_url=e.html_url,
                    pdf_url=e.pdf_url,
                    adapter_tag=e.adapter_tag,
                )
                for e in expectation_rows
            ]
            run.total = len(sources)
            run.processed = 0
            run.failed = 0
            await db.commit()

        provider_obj = build_index_provider(provider_row)

        async def on_result(outcome: ScanItemOutcome) -> None:
            await _upsert_result(db_factory, project_id, provider_id, outcome)

        async def on_progress(processed: int, failed: int) -> None:
            # Throttle progress writes: every 10 items, and always at the end.
            if processed % 10 and processed != len(sources):
                return
            async with db_factory() as pdb:
                prun = (
                    await pdb.execute(select(SourceScanRun).where(SourceScanRun.id == scan_id))
                ).scalar_one_or_none()
                if prun is not None:
                    prun.processed = processed
                    prun.failed = failed
                    await pdb.commit()

        await scan_sources(
            provider_obj,
            sources,
            concurrency=settings.source_scan_concurrency,
            on_result=on_result,
            on_progress=on_progress,
        )

        async with db_factory() as final_db:
            final_run = (
                await final_db.execute(select(SourceScanRun).where(SourceScanRun.id == scan_id))
            ).scalar_one_or_none()
            if final_run is not None:
                final_run.processed = len(sources)
                final_run.status = "completed"
                final_run.completed_at = datetime.now(timezone.utc)
                await final_db.commit()
    except Exception as e:
        logger.exception("Source scan run %s failed", scan_id)
        try:
            async with db_factory() as db:
                run = (
                    await db.execute(select(SourceScanRun).where(SourceScanRun.id == scan_id))
                ).scalar_one_or_none()
                if run is not None:
                    run.status = "failed"
                    run.error = str(e)
                    run.completed_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            logger.exception("Failed to record source scan error for %s", scan_id)
    finally:
        if provider_obj is not None:
            try:
                await provider_obj.aclose()
            except Exception:
                logger.debug("Provider aclose failed", exc_info=True)
