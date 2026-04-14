"""Pydantic schemas for fixes endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FixApplyResponse(BaseModel):
    id: UUID
    status: str = "applied"
    applied_at: datetime
