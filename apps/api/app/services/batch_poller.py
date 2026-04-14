"""Background poller for Azure OpenAI batch eval jobs.

Checks pending batch jobs every 60 seconds and processes results when complete.
Reads state from DB so it survives server restarts.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.db import async_session
from app.models.models import BatchEvalJob, EvalJob, EvalJobStatus, EvalSession

logger = logging.getLogger(__name__)

_poller_task: asyncio.Task | None = None

POLL_INTERVAL_SECONDS = 60
ACTIVE_STATUSES = ("submitted", "in_progress", "validating", "finalizing")


async def start_batch_poller() -> None:
    """Start the background polling loop. Called from app lifespan."""
    global _poller_task
    _poller_task = asyncio.create_task(_poll_loop())
    logger.info("Batch poller started")


async def stop_batch_poller() -> None:
    """Stop the polling loop. Called on shutdown."""
    global _poller_task
    if _poller_task:
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            pass
        _poller_task = None
    logger.info("Batch poller stopped")


async def _poll_loop() -> None:
    """Poll for active batch jobs every POLL_INTERVAL_SECONDS."""
    while True:
        try:
            await _check_all_batches()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Batch poller error")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _check_all_batches() -> None:
    """Check all active batch jobs and process any that completed."""
    async with async_session() as db:
        result = await db.execute(
            select(BatchEvalJob).where(BatchEvalJob.status.in_(ACTIVE_STATUSES))
        )
        pending_jobs = list(result.scalars().all())

        if not pending_jobs:
            return

        logger.info("Checking %d active batch job(s)", len(pending_jobs))

        for batch_job in pending_jobs:
            try:
                await _check_and_process(db, batch_job)
            except Exception:
                logger.exception("Error processing batch job %s", batch_job.id)


async def _check_and_process(db, batch_job: BatchEvalJob) -> None:
    """Check one batch job's status and process if complete."""
    from app.services.batch_llm_service import BatchLlmService

    batch_service = BatchLlmService()
    status_info = await batch_service.check_status(batch_job.batch_id)
    api_status = status_info["status"]

    logger.info(
        "Batch %s status: %s (completed: %d, failed: %d, total: %d)",
        batch_job.batch_id, api_status,
        status_info.get("completed", 0),
        status_info.get("failed", 0),
        status_info.get("total", 0),
    )

    # Update progress
    batch_job.completed_requests = status_info.get("completed", 0)
    batch_job.failed_requests = status_info.get("failed", 0)

    if api_status in ("validating", "in_progress", "finalizing"):
        batch_job.status = api_status
        await db.commit()
        return

    if api_status == "completed":
        from app.services.batch_eval_executor import process_batch_results
        await process_batch_results(batch_job, db)
        # Check if this completes a session
        await _maybe_finalize_session(db, batch_job)
        return

    if api_status in ("failed", "expired", "cancelled"):
        batch_job.status = api_status
        error_msg = f"Batch job {api_status}"
        if status_info.get("error_file_id"):
            try:
                errors = await batch_service.download_results(status_info["error_file_id"])
                if errors:
                    error_msg += f": {errors[0].get('error', {}).get('message', '')}"
            except Exception:
                pass
        batch_job.error = error_msg[:2000]
        batch_job.completed_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

        # Mark parent eval job as failed
        job_result = await db.execute(
            select(EvalJob).where(EvalJob.id == batch_job.eval_job_id)
        )
        job = job_result.scalar_one_or_none()
        if job:
            job.status = EvalJobStatus.failed
            job.error = error_msg[:2000]
            job.completed_at = batch_job.completed_at
            existing_log = job.log or ""
            job.log = existing_log + f"\nERROR: {error_msg}"

        await db.commit()

        # Check if this affects a session
        await _maybe_finalize_session(db, batch_job)


async def _maybe_finalize_session(db, batch_job: BatchEvalJob) -> None:
    """If the batch job's eval job belongs to a session, check if all sibling batches are done."""
    # Load the parent eval job to get session info
    job_result = await db.execute(select(EvalJob).where(EvalJob.id == batch_job.eval_job_id))
    job = job_result.scalar_one_or_none()
    if not job or not job.config:
        return

    session_id = job.config.get("session_id")
    if not session_id:
        return

    # Find all eval jobs in this session
    sibling_jobs_result = await db.execute(
        select(EvalJob).where(
            EvalJob.config["session_id"].astext == session_id,
        )
    )
    sibling_jobs = list(sibling_jobs_result.scalars().all())

    # Check if all are done (completed or failed, not batch_pending/running/pending)
    all_done = all(
        j.status in (EvalJobStatus.completed, EvalJobStatus.failed, EvalJobStatus.cancelled)
        for j in sibling_jobs
    )

    if not all_done:
        return

    # Finalize the session
    from datetime import datetime, timezone
    from uuid import UUID

    session_result = await db.execute(
        select(EvalSession).where(EvalSession.id == UUID(session_id))
    )
    session = session_result.scalar_one_or_none()
    if session and session.status not in (EvalJobStatus.completed, EvalJobStatus.failed):
        any_failed = any(j.status == EvalJobStatus.failed for j in sibling_jobs)
        session.status = EvalJobStatus.failed if any_failed else EvalJobStatus.completed
        session.completed_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info("Session %s finalized: %s", session_id, session.status)
