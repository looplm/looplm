"""Pydantic schemas for integrations endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# Allowed auto-sync cadences (minutes). NULL/None = disabled. Bounded so the
# source API isn't hammered. Mirrors the preset dropdown in the web UI.
ALLOWED_SYNC_INTERVALS = {15, 30, 60, 180, 360, 720, 1440}


def _validate_sync_interval(value: Optional[int]) -> Optional[int]:
    if value is not None and value not in ALLOWED_SYNC_INTERVALS:
        allowed = ", ".join(str(v) for v in sorted(ALLOWED_SYNC_INTERVALS))
        raise ValueError(f"auto_sync_interval_minutes must be one of: {allowed} (or null)")
    return value


class IntegrationCreate(BaseModel):
    type: str = Field(..., pattern="^(langfuse|langsmith|json_file|looplm)$")
    name: str = Field(..., max_length=255)
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    auto_sync_interval_minutes: Optional[int] = None

    @field_validator("auto_sync_interval_minutes")
    @classmethod
    def _check_interval(cls, v: Optional[int]) -> Optional[int]:
        return _validate_sync_interval(v)


class IntegrationUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    auto_sync_interval_minutes: Optional[int] = None

    @field_validator("auto_sync_interval_minutes")
    @classmethod
    def _check_interval(cls, v: Optional[int]) -> Optional[int]:
        return _validate_sync_interval(v)


class IntegrationResponse(BaseModel):
    id: UUID
    type: str
    name: str
    base_url: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    sync_status: str = "never"
    last_synced_at: Optional[datetime] = None
    last_sync_error: Optional[str] = None
    sync_progress_current: Optional[int] = None
    sync_progress_total: Optional[int] = None
    sync_started_at: Optional[datetime] = None
    sync_phase: Optional[str] = None
    sync_message: Optional[str] = None
    sync_since: Optional[datetime] = None
    last_received_at: Optional[datetime] = None
    auto_sync_interval_minutes: Optional[int] = None
    next_sync_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IntegrationListResponse(BaseModel):
    data: list[IntegrationResponse]


class IngestKeyCreate(BaseModel):
    name: str = Field("default", max_length=255)


class IngestKeyResponse(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class IngestKeyCreateResponse(IngestKeyResponse):
    # The plaintext key — returned ONLY on creation, never again.
    key: str


class IngestKeyListResponse(BaseModel):
    data: list[IngestKeyResponse]


class SyncRequest(BaseModel):
    since: Optional[datetime] = None
    update_existing: bool = False


class SyncResponse(BaseModel):
    message: str = "Sync started"
    integration_id: UUID
    sync_status: str = "syncing"
