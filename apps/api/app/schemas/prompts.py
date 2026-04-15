"""Pydantic schemas for prompt import & analysis."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PromptBase(BaseModel):
    name: str
    template: str
    version: int = 1
    variables: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class PromptOut(PromptBase):
    id: str
    integration_id: str
    external_id: str
    source: str = ""
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromptListResponse(BaseModel):
    data: list[PromptOut] = Field(default_factory=list)
    total: int = 0


class PromptSyncResponse(BaseModel):
    synced: int = 0
    message: str = ""


class PromptImportItem(BaseModel):
    name: str
    template: str
    version: int = 1
    variables: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class PromptImportRequest(BaseModel):
    prompts: list[PromptImportItem]
    filename: str = "import.json"


class PromptVersionDiff(BaseModel):
    version_a: int
    version_b: int
    diff: str = ""


class AntiPattern(BaseModel):
    pattern: str
    description: str
    severity: str = "medium"
    location: str = ""


class PromptReviewResult(BaseModel):
    id: str = ""
    prompt_id: str
    anti_patterns: list[AntiPattern] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    rewritten_prompt: str = ""
    reviewed_at: datetime | None = None
    model: str = ""

    model_config = {"from_attributes": True}


class PromptReviewListResponse(BaseModel):
    data: list[PromptReviewResult] = Field(default_factory=list)
    total: int = 0
