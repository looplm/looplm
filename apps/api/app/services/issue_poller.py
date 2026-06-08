"""Background poller for autonomous issue detection + diagnosis.

Every ``issue_detection_interval_minutes`` it runs one detect→diagnose pass per
project over the trailing ``issue_detection_window_days``. This is the
"autonomous background loop" the engine's docstring anticipated; detection still
falls back to deterministic clustering when no LLM is configured, while
diagnosis is skipped without one.

Gated by ``settings.issue_detection_enabled`` (off by default).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import distinct, select

from app.config import settings
from app.db import async_session
from app.models.models import Integration
from app.services.analysis_llm import AnalysisLlmConfigError, AnalysisLlmService
from app.services.engine.engine_service import detect_issues, diagnose_issues

logger = logging.getLogger(__name__)

_poller_task: asyncio.Task | None = None


async def start_issue_poller() -> None:
    """Start the background loop (called from app lifespan). No-op if disabled."""
    global _poller_task
    if not settings.issue_detection_enabled:
        logger.info("Issue detection poller disabled (issue_detection_enabled=False)")
        return
    _poller_task = asyncio.create_task(_poll_loop())
    logger.info("Issue detection poller started")


async def stop_issue_poller() -> None:
    global _poller_task
    if _poller_task:
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            pass
        _poller_task = None
    logger.info("Issue detection poller stopped")


async def _poll_loop() -> None:
    interval = max(1, settings.issue_detection_interval_minutes) * 60
    while True:
        try:
            await run_detection_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Issue detection poller error")
        await asyncio.sleep(interval)


async def run_detection_cycle() -> int:
    """Run detect + diagnose for every project with integrations. Returns project count."""
    try:
        llm: AnalysisLlmService | None = AnalysisLlmService()
    except AnalysisLlmConfigError:
        llm = None

    since = datetime.now(timezone.utc) - timedelta(days=settings.issue_detection_window_days)

    async with async_session() as db:
        project_ids = (
            await db.execute(select(distinct(Integration.project_id)))
        ).scalars().all()

        for pid in project_ids:
            try:
                await detect_issues(db, pid, since=since, llm=llm)
                await diagnose_issues(db, pid, llm=llm)
            except Exception:
                logger.exception("Issue detection failed for project %s", pid)
                await db.rollback()

    return len(project_ids)
