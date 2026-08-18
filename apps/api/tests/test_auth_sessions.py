"""Refresh-session service tests that reproduce production session semantics.

The `client` fixture overrides `get_db` with a session that never rolls back, so a request-level
test cannot tell a flushed write from a committed one. Real `get_db` rolls back on any exception
(`app/db.py`), which is exactly the path a replayed refresh token takes: revoke the family, then
raise 401. These tests drive the service directly and roll back the way production does.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth import decode_refresh_token
from app.models.auth_session import RefreshSession
from app.services.auth_sessions import issue_refresh, revoke, rotate


async def _family_rows(db, family_id):
    return (
        await db.execute(select(RefreshSession).where(RefreshSession.family_id == family_id))
    ).scalars().all()


@pytest.mark.asyncio
async def test_replay_revocation_survives_rollback(db_session, test_user):
    """The family revocation must outlive the 401 that follows it."""
    first = await issue_refresh(db_session, test_user.id)
    _user, _jti, family_id = decode_refresh_token(first)

    _user_id, second = await rotate(db_session, first)
    assert second != first

    with pytest.raises(HTTPException) as exc:
        await rotate(db_session, first)
    assert exc.value.status_code == 401

    # What get_db does when the handler raises.
    await db_session.rollback()

    rows = await _family_rows(db_session, family_id)
    assert len(rows) == 2
    assert all(r.revoked_at is not None for r in rows), (
        "replaying a consumed token must revoke the whole chain, including the successor"
    )

    # And the successor is genuinely dead.
    with pytest.raises(HTTPException):
        await rotate(db_session, second)


@pytest.mark.asyncio
async def test_rotation_keeps_one_live_session_per_chain(db_session, test_user):
    token = await issue_refresh(db_session, test_user.id)
    _user, _jti, family_id = decode_refresh_token(token)

    for _ in range(3):
        _user_id, token = await rotate(db_session, token)

    rows = await _family_rows(db_session, family_id)
    live = [r for r in rows if r.revoked_at is None]
    assert len(rows) == 4
    assert len(live) == 1
    assert str(live[0].id) == str(decode_refresh_token(token)[1])


@pytest.mark.asyncio
async def test_logout_revocation_survives_rollback(db_session, test_user):
    token = await issue_refresh(db_session, test_user.id)
    _user, _jti, family_id = decode_refresh_token(token)

    await revoke(db_session, token)
    await db_session.rollback()

    rows = await _family_rows(db_session, family_id)
    assert all(r.revoked_at is not None for r in rows)


@pytest.mark.asyncio
async def test_revoke_ignores_a_malformed_token(db_session):
    """Logout is best-effort - a garbage token must not raise."""
    await revoke(db_session, "not.a.token")
