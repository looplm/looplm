"""Tests for the auto-sync poller's due-detection and claim logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.models import Integration, IntegrationType, SyncStatus
from app.services import sync_poller


def _naive(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on round-trip; compare timestamps tz-agnostically."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None)


class _FakeSessionCtx:
    """Async context manager that hands the poller our test session instead of
    opening a fresh one against the (non-test) engine, and doesn't close it."""

    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


def _integration(project_id, **kwargs) -> Integration:
    return Integration(
        id=uuid4(),
        project_id=project_id,
        type=IntegrationType.langfuse,
        name=f"integ-{uuid4().hex[:8]}",
        api_key=b"fake-encrypted-key",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_check_due_syncs_claims_only_due_integrations(db_session, test_project, monkeypatch):
    monkeypatch.setattr(sync_poller, "async_session", lambda: _FakeSessionCtx(db_session))

    spawned: list = []
    monkeypatch.setattr(sync_poller, "_spawn_auto_sync", lambda iid: spawned.append(iid))

    now = datetime.now(timezone.utc)
    due = _integration(
        test_project.id,
        auto_sync_interval_minutes=15,
        next_sync_at=now - timedelta(minutes=1),
    )
    never_run = _integration(
        test_project.id,
        auto_sync_interval_minutes=60,
        next_sync_at=None,  # NULL = due immediately
    )
    not_yet = _integration(
        test_project.id,
        auto_sync_interval_minutes=15,
        next_sync_at=now + timedelta(hours=1),
    )
    disabled = _integration(
        test_project.id,
        auto_sync_interval_minutes=None,
        next_sync_at=now - timedelta(minutes=1),
    )
    already_syncing = _integration(
        test_project.id,
        auto_sync_interval_minutes=15,
        next_sync_at=now - timedelta(minutes=1),
        sync_status=SyncStatus.syncing,
    )
    db_session.add_all([due, never_run, not_yet, disabled, already_syncing])
    await db_session.commit()

    await sync_poller._check_due_syncs()

    # Only the two due integrations were launched.
    assert set(spawned) == {due.id, never_run.id}

    now_naive = _naive(now)

    # Claimed integrations are marked syncing and their next run is pushed out.
    await db_session.refresh(due)
    assert due.sync_status == SyncStatus.syncing
    assert _naive(due.next_sync_at) is not None and _naive(due.next_sync_at) > now_naive
    # ~15 minutes ahead of the claim time (allow slack for clock between calls).
    assert _naive(due.next_sync_at) - now_naive >= timedelta(minutes=14)

    await db_session.refresh(never_run)
    assert never_run.sync_status == SyncStatus.syncing
    assert _naive(never_run.next_sync_at) is not None and _naive(never_run.next_sync_at) > now_naive

    # Untouched: not-yet-due, disabled, and already-syncing.
    await db_session.refresh(not_yet)
    assert _naive(not_yet.next_sync_at) > now_naive and not_yet.sync_status != SyncStatus.syncing
    await db_session.refresh(disabled)
    assert disabled.sync_status != SyncStatus.syncing
    await db_session.refresh(already_syncing)
    assert already_syncing.id not in spawned


@pytest.mark.asyncio
async def test_check_due_syncs_no_due_is_noop(db_session, test_project, monkeypatch):
    monkeypatch.setattr(sync_poller, "async_session", lambda: _FakeSessionCtx(db_session))
    spawned: list = []
    monkeypatch.setattr(sync_poller, "_spawn_auto_sync", lambda iid: spawned.append(iid))

    now = datetime.now(timezone.utc)
    db_session.add(
        _integration(test_project.id, auto_sync_interval_minutes=None, next_sync_at=None)
    )
    db_session.add(
        _integration(
            test_project.id,
            auto_sync_interval_minutes=60,
            next_sync_at=now + timedelta(hours=2),
        )
    )
    await db_session.commit()

    await sync_poller._check_due_syncs()

    assert spawned == []
