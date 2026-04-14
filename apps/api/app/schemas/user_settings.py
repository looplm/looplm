"""Schemas for user settings API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class UserSettingsUpdate(BaseModel):
    llm_provider: Literal["openai", "azure_openai"] | None = None
    openai_api_key: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str | None = None


class UserSettingsResponse(BaseModel):
    llm_provider: str
    openai_api_key: str
    azure_openai_api_key: str
    azure_openai_endpoint: str
    azure_openai_deployment: str
    azure_openai_api_version: str
