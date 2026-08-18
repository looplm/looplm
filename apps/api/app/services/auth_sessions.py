"""Refresh-token session lifecycle: issue, rotate, revoke.

A refresh token is only honoured while its `RefreshSession` row is live. Rotation revokes the
presented row and issues a successor in the same family; replaying a revoked or unknown token
revokes the entire family, on the assumption that a replay means the token leaked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_refresh_token,
    decode_refresh_token,
)
from app.models.auth_session import RefreshSession

# Rows are kept a little past expiry so a replay of a just-expired token still trips the
# family revocation rather than looking like an unknown token.
_PRUNE_GRACE = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

_INVALID = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite (tests) hands back naive datetimes; treat them as UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def issue_refresh(
    db: AsyncSession, user_id: UUID, *, family_id: UUID | None = None
) -> str:
    """Mint a refresh token and persist its session row."""
    token, jti, family, expires_at = create_refresh_token(user_id, family_id=family_id)
    db.add(
        RefreshSession(id=jti, user_id=user_id, family_id=family, expires_at=expires_at)
    )
    await db.flush()
    return token


async def revoke_family(db: AsyncSession, family_id: UUID) -> None:
    """Revoke every live session in a rotation chain.

    Commits rather than flushes: the caller usually raises 401 straight after, and `get_db`
    rolls back on an exception - a flushed-only revocation would be discarded, leaving the
    replayed chain live. This is the one write that must outlive the failed request.
    """
    await db.execute(
        update(RefreshSession)
        .where(RefreshSession.family_id == family_id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def rotate(db: AsyncSession, token: str) -> tuple[UUID, str]:
    """Consume a refresh token and return ``(user_id, new_refresh_token)``.

    Raises 401 when the token is malformed, expired, unknown, or already used.
    """
    user_id, jti, family_id = decode_refresh_token(token)

    row = (
        await db.execute(select(RefreshSession).where(RefreshSession.id == jti))
    ).scalar_one_or_none()

    if row is None:
        # Unknown jti with a valid signature: either a token from before sessions existed, or a
        # forgery-by-replay of a pruned row. Revoke the family when we can identify it.
        if family_id is not None:
            await revoke_family(db, family_id)
        raise _INVALID

    now = datetime.now(timezone.utc)
    if row.revoked_at is not None or (_aware(row.expires_at) or now) <= now:
        await revoke_family(db, row.family_id)
        raise _INVALID
    if row.user_id != user_id:
        await revoke_family(db, row.family_id)
        raise _INVALID

    row.revoked_at = now
    await db.flush()
    new_token = await issue_refresh(db, user_id, family_id=row.family_id)
    await _prune_expired(db)
    return user_id, new_token


async def revoke(db: AsyncSession, token: str) -> None:
    """Revoke the presented token's whole family. Never raises - logout is best-effort."""
    try:
        _user_id, jti, family_id = decode_refresh_token(token)
    except HTTPException:
        return
    row = (
        await db.execute(select(RefreshSession).where(RefreshSession.id == jti))
    ).scalar_one_or_none()
    target = row.family_id if row is not None else family_id
    if target is not None:
        await revoke_family(db, target)


async def _prune_expired(db: AsyncSession) -> None:
    await db.execute(
        RefreshSession.__table__.delete().where(
            RefreshSession.expires_at < datetime.now(timezone.utc) - _PRUNE_GRACE
        )
    )
