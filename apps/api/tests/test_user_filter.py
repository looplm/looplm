"""Tests for the shared include/exclude end-user filter."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models.models import Trace, TraceStatus
from app.services.user_filter import user_id_filters


async def _seed(db_session, integration, user_ids: list[str | None]) -> None:
    for i, user_id in enumerate(user_ids):
        db_session.add(
            Trace(
                id=uuid4(),
                integration_id=integration.id,
                external_id=f"ext-{i}",
                name=f"trace-{i}",
                user_id=user_id,
                start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                status=TraceStatus.success,
            )
        )
    await db_session.commit()


async def _matching_user_ids(db_session, integration, *, include=None, exclude=None) -> set:
    result = await db_session.execute(
        select(Trace.user_id).where(
            Trace.integration_id == integration.id,
            *user_id_filters(include, exclude),
        )
    )
    return set(result.scalars().all())


@pytest.mark.asyncio
async def test_no_filters_matches_everything(db_session, test_integration):
    await _seed(db_session, test_integration, ["qa-1", "customer-1", None])
    assert await _matching_user_ids(db_session, test_integration) == {"qa-1", "customer-1", None}


@pytest.mark.asyncio
async def test_include_keeps_only_listed_ids(db_session, test_integration):
    await _seed(db_session, test_integration, ["qa-1", "customer-1", None])
    matched = await _matching_user_ids(db_session, test_integration, include=["qa-1"])
    assert matched == {"qa-1"}


@pytest.mark.asyncio
async def test_exclude_keeps_traces_without_a_user_id(db_session, test_integration):
    """Excluding internal users must not hide anonymous traffic (NULL NOT IN … is NULL)."""
    await _seed(db_session, test_integration, ["qa-1", "customer-1", None])
    matched = await _matching_user_ids(db_session, test_integration, exclude=["qa-1"])
    assert matched == {"customer-1", None}


@pytest.mark.asyncio
async def test_include_and_exclude_intersect(db_session, test_integration):
    await _seed(db_session, test_integration, ["qa-1", "customer-1", None])
    matched = await _matching_user_ids(
        db_session, test_integration, include=["qa-1", "customer-1"], exclude=["qa-1"]
    )
    assert matched == {"customer-1"}


@pytest.mark.asyncio
async def test_counts_are_filtered_too(db_session, test_integration):
    """Guards the count queries that apply the same criteria alongside the row query."""
    await _seed(db_session, test_integration, ["qa-1", "qa-1", "customer-1", None])
    total = await db_session.execute(
        select(func.count(Trace.id)).where(
            Trace.integration_id == test_integration.id,
            *user_id_filters(None, ["qa-1"]),
        )
    )
    assert total.scalar() == 2
