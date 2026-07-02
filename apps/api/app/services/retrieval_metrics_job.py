"""Detached runner for a labels-path retrieval-metrics compute.

Executed as an in-process ``asyncio`` task (spawned by ``routers/retrieval.py``) with its own DB
session, so the panel's HTTP calls stay short and a reload/timeout can't reset the socket
mid-compute. The result is written into the Redis metrics cache by the compute functions
themselves; this runner only drives the ``RetrievalMetricsJob`` status row, capturing the exception
message and traceback on failure so the UI can surface — and copy — the real error.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from uuid import UUID

from app.config import settings
from app.db import async_session
from app.models.project import Project
from app.models.retrieval_metrics_jobs import RetrievalMetricsJob
from app.services.retrieval_labels_metrics import (
    compute_by_stage_metrics,
    compute_overall_labels_metrics,
    resolve_datasets,
)

logger = logging.getLogger(__name__)


async def run_metrics_job(job_id: UUID, refresh: bool = False) -> None:
    """Run one metrics compute to completion, updating its status row throughout.

    ``refresh`` bypasses the result + probe caches (Recompute); otherwise a warm cache is reused.
    """
    async with async_session() as db:
        job = await db.get(RetrievalMetricsJob, job_id)
        if job is None:
            return
        # A stop/superseding restart may have already settled it; don't resurrect.
        if job.status not in ("pending", "running"):
            return
        job.status = "running"
        await db.commit()

        project = await db.get(Project, job.project_id)
        try:
            if project is None:
                raise ValueError("Project not found for compute job")
            dataset_uuids = [UUID(x) for x in (job.dataset_ids or [])]
            datasets = await resolve_datasets(db, project, dataset_uuids or None)
            if job.view == "byStage":
                await compute_by_stage_metrics(db, project, datasets, job.gold_source, refresh)
            else:
                await compute_overall_labels_metrics(db, project, datasets, job.gold_source, refresh)
            job.status = "completed"
            job.error = None
            job.trace = None
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI via the job row
            logger.exception("Retrieval metrics compute job %s failed", job_id)
            job.status = "failed"
            job.error = str(exc) or exc.__class__.__name__
            # Match the sanitized-500 contract: only expose the traceback in debug builds.
            job.trace = (
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                if settings.debug
                else None
            )
        finally:
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
