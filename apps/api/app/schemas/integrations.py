"""Pydantic schemas for integrations endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class IntegrationCreate(BaseModel):
    type: str = Field(..., pattern="^(langfuse|langsmith|json_file)$")
    name: str = Field(..., max_length=255)
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)


class IntegrationUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    config: Optional[dict[str, Any]] = None


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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IntegrationListResponse(BaseModel):
    data: list[IntegrationResponse]


class SyncRequest(BaseModel):
    since: Optional[datetime] = None
    update_existing: bool = False


class SyncResponse(BaseModel):
    message: str = "Sync started"
    integration_id: UUID
    sync_status: str = "syncing"
