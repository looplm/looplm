"""Background poller for scheduled (auto) trace syncs.

Every POLL_INTERVAL_SECONDS it scans for integrations whose auto-sync schedule
is due (auto_sync_interval_minutes set and next_sync_at in the past) and that
aren't already syncing, then kicks off a sync for each.

Scheduling state lives in the DB (auto_sync_interval_minutes, next_sync_at) so
it survives restarts. The poller "claims" a due integration by advancing
next_sync_at and marking it 'syncing' on its own committed session *before*
spawning the work — so a crashed or failed run still backs off to the next
interval instead of being retried every tick, and the single-threaded loop
can't double-spawn. The actual sync reuses the same background runner as manual
syncs, so the Stop button and restart reconciliation keep working unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.db import async_session
from app.models.models import Integration, SyncStatus

logger = logging.getLogger(__name__)

_poller_task: asyncio.Task | None = None

POLL_INTERVAL_SECONDS = 60


async def start_sync_poller() -> None:
    """Start the background polling loop. Called from app lifespan."""
    global _poller_task
    _poller_task = asyncio.create_task(_poll_loop())
    logger.info("Sync poller started")


async def stop_sync_poller() -> None:
    """Stop the polling loop. Called on shutdown."""
    global _poller_task
    if _poller_task:
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            pass
        _poller_task = None
    logger.info("Sync poller stopped")


async def _poll_loop() -> None:
    """Check for due auto-syncs every POLL_INTERVAL_SECONDS."""
    while True:
        try:
            await _check_due_syncs()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Sync poller error")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _check_due_syncs() -> None:
    """Claim and launch a sync for every integration whose schedule is due."""
    async with async_session() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(Integration).where(
                Integration.auto_sync_interval_minutes.isnot(None),
                Integration.sync_status != SyncStatus.syncing,
                or_(Integration.next_sync_at.is_(None), Integration.next_sync_at <= now),
            )
        )
        due = list(result.scalars().all())
        if not due:
            return

        logger.info("Auto-sync: %d integration(s) due", len(due))

        for integration in due:
            # Claim it: advance next_sync_at FIRST so a crash/error still backs
            # off, then mark syncing — matching trigger_sync's state setup.
            integration.next_sync_at = now + timedelta(
                minutes=integration.auto_sync_interval_minutes
            )
            integration.sync_status = SyncStatus.syncing
            integration.last_sync_error = None
            integration.sync_progress_current = None
            integration.sync_progress_total = None
            integration.sync_started_at = now
            integration.sync_phase = None
            integration.sync_message = None
            integration.sync_since = None
            await db.commit()
            _spawn_auto_sync(integration.id)


def _spawn_auto_sync(integration_id) -> None:
    """Run the sync via the same background machinery manual syncs use, so the
    Stop button (which cancels tasks in _sync_tasks) keeps working."""
    from app.routers.integrations import _run_sync_background, _sync_tasks

    task = asyncio.create_task(_run_sync_background(integration_id))
    _sync_tasks[integration_id] = task
