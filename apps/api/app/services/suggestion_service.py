"""Suggestion service — manages fix suggestion lifecycle."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import FixStatus, FixSuggestion


async def apply_fix(fix_id: UUID, db: AsyncSession) -> FixSuggestion:
    """Mark a fix suggestion as applied."""
    result = await db.execute(select(FixSuggestion).where(FixSuggestion.id == fix_id))
    fix = result.scalar_one_or_none()
    if not fix:
        raise ValueError(f"Fix {fix_id} not found")
    if fix.status != FixStatus.pending:
        raise ValueError(f"Fix {fix_id} is already {fix.status.value}")

    fix.status = FixStatus.applied
    await db.commit()
    return fix


async def dismiss_fix(fix_id: UUID, db: AsyncSession) -> FixSuggestion:
    """Mark a fix suggestion as dismissed."""
    result = await db.execute(select(FixSuggestion).where(FixSuggestion.id == fix_id))
    fix = result.scalar_one_or_none()
    if not fix:
        raise ValueError(f"Fix {fix_id} not found")

    fix.status = FixStatus.dismissed
    await db.commit()
    return fix
