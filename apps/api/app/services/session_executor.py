"""Session executor — orchestrates running multiple experiments as separate eval runs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.db import async_session
from app.models.models import EvalJob, EvalJobStatus, EvalSession, Experiment
from app.services.eval_executor import run_eval
from app.services.batch_eval_executor import run_eval_batch

logger = logging.getLogger(__name__)


async def run_session(
    session_id: UUID,
    project_id: UUID,
    dataset_ids: list[UUID] | None,
    experiment_ids: list[UUID],
    concurrency: int,
    project_settings: dict | None = None,
    max_turns: int = 1,
    use_batch: bool = False,
) -> None:
    """Run each experiment sequentially, creating a separate EvalRun per experiment."""
    async with async_session() as db:
        # Load session
        result = await db.execute(select(EvalSession).where(EvalSession.id == session_id))
        session = result.scalar_one()
        session.status = EvalJobStatus.running
        session.progress_total = len(experiment_ids)
        session.progress_current = 0
        await db.commit()

        completed = 0
        failed_any = False

        for exp_id in experiment_ids:
            # Load experiment
            exp_result = await db.execute(
                select(Experiment).where(Experiment.id == exp_id)
            )
            experiment = exp_result.scalar_one_or_none()
            if not experiment:
                logger.error("Session %s: experiment %s not found, skipping", session_id, exp_id)
                failed_any = True
                continue

            # Resolve filter_mode from experiment variables or default
            exp_vars = experiment.variables or {}
            filter_mode = exp_vars.get("filter_mode", "as_configured")

            # Create a job for this experiment run
            job = EvalJob(
                project_id=project_id,
                test_suite=f"Session experiment: {experiment.name}",
                dataset_ids=[str(d) for d in dataset_ids] if dataset_ids else None,
                status=EvalJobStatus.pending,
                config={
                    "filter_mode": filter_mode,
                    "concurrency": concurrency,
                    "max_turns": max_turns,
                    "experiment_id": str(exp_id),
                    "session_id": str(session_id),
                },
            )
            db.add(job)
            await db.flush()

            try:
                run_fn = run_eval_batch if use_batch else run_eval
                await run_fn(
                    job_id=job.id,
                    project_id=project_id,
                    dataset_ids=dataset_ids,
                    concurrency=concurrency,
                    db=db,
                    project_settings=project_settings,
                    filter_mode=filter_mode,
                    max_turns=max_turns,
                    experiment_variables=exp_vars if exp_vars else None,
                    session_id=session_id,
                    experiment_id=exp_id,
                    experiment_name=experiment.name,
                )
            except Exception as e:
                logger.error(
                    "Session %s: experiment %s (%s) failed: %s",
                    session_id, exp_id, experiment.name, e,
                )
                failed_any = True

            completed += 1
            session.progress_current = completed
            await db.commit()

        # Finalize session — for batch mode, check if any jobs are still batch_pending
        if use_batch:
            # Check if any experiment jobs are in batch_pending state
            from sqlalchemy import select as sel
            pending_result = await db.execute(
                sel(EvalJob).where(
                    EvalJob.config["session_id"].astext == str(session_id),
                    EvalJob.status == EvalJobStatus.batch_pending,
                )
            )
            has_pending = pending_result.scalar_one_or_none() is not None
            if has_pending:
                session.status = EvalJobStatus.batch_pending
                await db.commit()
                logger.info("Session %s: %d/%d experiments submitted, awaiting batch results", session_id, completed, len(experiment_ids))
                return

        session.status = EvalJobStatus.failed if failed_any else EvalJobStatus.completed
        session.completed_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info("Session %s completed: %d/%d experiments", session_id, completed, len(experiment_ids))


async def run_session_background(
    session_id: UUID,
    project_id: UUID,
    dataset_ids: list[UUID] | None,
    experiment_ids: list[UUID],
    concurrency: int,
    project_settings: dict | None = None,
    max_turns: int = 1,
    use_batch: bool = False,
) -> None:
    """Run session in a background task with error handling."""
    import asyncio

    try:
        await run_session(
            session_id=session_id,
            project_id=project_id,
            dataset_ids=dataset_ids,
            experiment_ids=experiment_ids,
            concurrency=concurrency,
            project_settings=project_settings,
            max_turns=max_turns,
            use_batch=use_batch,
        )
    except asyncio.CancelledError:
        logger.info("Session %s cancelled", session_id)
    except Exception as e:
        logger.error("Session %s failed: %s", session_id, e)
        try:
            async with async_session() as db:
                result = await db.execute(select(EvalSession).where(EvalSession.id == session_id))
                session = result.scalar_one_or_none()
                if session and session.status not in (EvalJobStatus.completed, EvalJobStatus.cancelled):
                    session.status = EvalJobStatus.failed
                    session.completed_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            logger.error("Failed to update session %s error status", session_id)
