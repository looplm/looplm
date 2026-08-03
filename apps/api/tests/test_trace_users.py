"""Tests for GET /api/traces/users — the raw-user-id list behind the user directory.

The display name lives in trace metadata under ``userName`` (the spelling every other reader in
the codebase uses: ``dataset_suggestions``, ``feedback_eval``). This endpoint used to read only
lowercase ``username``, which meant the Settings → Users table had no names to suggest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.models import Trace, TraceStatus

USERS_URL = "/api/traces/users"


async def _add_trace(db_session, integration, user_id, metadata=None, i=0):
    db_session.add(
        Trace(
            id=uuid4(),
            integration_id=integration.id,
            external_id=f"ext-{uuid4().hex[:8]}",
            name=f"trace-{i}",
            user_id=user_id,
            trace_metadata=metadata,
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            status=TraceStatus.success,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_camel_case_username_is_returned(client, auth_headers, db_session, test_integration):
    await _add_trace(db_session, test_integration, "u-1", {"userName": "Antonia"})
    rows = (await client.get(USERS_URL, headers=auth_headers)).json()
    assert rows == [{"user_id": "u-1", "username": "Antonia", "trace_count": 1}]


@pytest.mark.asyncio
async def test_lowercase_username_still_works(client, auth_headers, db_session, test_integration):
    await _add_trace(db_session, test_integration, "u-1", {"username": "legacy"})
    rows = (await client.get(USERS_URL, headers=auth_headers)).json()
    assert rows[0]["username"] == "legacy"


@pytest.mark.asyncio
async def test_camel_case_wins_over_lowercase(client, auth_headers, db_session, test_integration):
    await _add_trace(db_session, test_integration, "u-1", {"userName": "Ada", "username": "old"})
    rows = (await client.get(USERS_URL, headers=auth_headers)).json()
    assert rows[0]["username"] == "Ada"


@pytest.mark.asyncio
async def test_name_found_even_when_some_traces_lack_it(
    client, auth_headers, db_session, test_integration
):
    """Only some requests carry the name, so the aggregate must not lose it."""
    await _add_trace(db_session, test_integration, "u-1", None, i=1)
    await _add_trace(db_session, test_integration, "u-1", {"userName": "Sonja"}, i=2)
    rows = (await client.get(USERS_URL, headers=auth_headers)).json()
    assert rows == [{"user_id": "u-1", "username": "Sonja", "trace_count": 2}]


@pytest.mark.asyncio
async def test_trace_counts_and_blank_ids(client, auth_headers, db_session, test_integration):
    for i in range(3):
        await _add_trace(db_session, test_integration, "busy", {"userName": "Tim"}, i=i)
    await _add_trace(db_session, test_integration, "quiet", None, i=9)
    await _add_trace(db_session, test_integration, None, None, i=10)
    await _add_trace(db_session, test_integration, "", None, i=11)

    rows = (await client.get(USERS_URL, headers=auth_headers)).json()
    by_id = {r["user_id"]: r for r in rows}
    assert set(by_id) == {"busy", "quiet"}, "null and empty user ids are not directory entries"
    assert by_id["busy"]["trace_count"] == 3
    assert by_id["busy"]["username"] == "Tim"
    assert by_id["quiet"]["username"] is None
