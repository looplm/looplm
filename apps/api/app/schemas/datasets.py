"""Pydantic schemas for test dataset endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.evaluations import PaginationInfo


# --- Dataset schemas ---

class TestDatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class TestDatasetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    tags: Optional[list[str]] = None


class TestDatasetItem(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    tags: list[str]
    test_count: int
    needs_work_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TestDatasetListResponse(BaseModel):
    data: list[TestDatasetItem]
    pagination: PaginationInfo


# --- Test case schemas ---

class TestCaseCreate(BaseModel):
    test_id: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=1)
    expected_answer: Optional[str] = None
    expected_sources: list[str] = Field(default_factory=list)
    context_filters: dict[str, str] = Field(default_factory=dict)
    team_filter: list[str] = Field(default_factory=list)
    tag_filter: list[str] = Field(default_factory=list)
    message_count: Optional[int] = None
    has_summary: bool = False
    folder: Optional[str] = None
    document: Optional[str] = None
    expected_page_urls: list[str] = Field(default_factory=list)
    expected_source_types: list[str] = Field(default_factory=list)
    max_answer_length: Optional[int] = None
    follow_up_prompts: Optional[list[dict[str, Any]]] = None
    source_feedback_id: Optional[UUID] = None
    source_trace_id: Optional[UUID] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestCaseUpdate(BaseModel):
    test_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    prompt: Optional[str] = Field(default=None, min_length=1)
    expected_answer: Optional[str] = None
    expected_sources: Optional[list[str]] = None
    context_filters: Optional[dict[str, str]] = None
    team_filter: Optional[list[str]] = None
    tag_filter: Optional[list[str]] = None
    message_count: Optional[int] = None
    has_summary: Optional[bool] = None
    folder: Optional[str] = None
    document: Optional[str] = None
    expected_page_urls: Optional[list[str]] = None
    expected_source_types: Optional[list[str]] = None
    max_answer_length: Optional[int] = None
    follow_up_prompts: Optional[list[dict[str, Any]]] = None
    tags: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None
    status: Optional[str] = Field(default=None, pattern="^(active|needs_work)$")
    status_note: Optional[str] = None


class ExpectedUrlsAdd(BaseModel):
    """Append URLs to a test case's expected_page_urls, keyed by its test_id.

    Used by the eval results view to promote retrieved source URLs into the
    expected set. ``test_id`` may carry the executor's ``[filtered]``/
    ``[unfiltered]`` variant suffix; the router strips it before lookup.
    """

    test_id: str = Field(min_length=1, max_length=300)
    urls: list[str] = Field(min_length=1)


class TestCaseItem(BaseModel):
    id: UUID
    dataset_id: UUID
    test_id: str
    prompt: str
    expected_answer: Optional[str] = None
    expected_sources: list[str]
    context_filters: dict[str, str]
    team_filter: list[str]
    tag_filter: list[str]
    message_count: Optional[int] = None
    has_summary: bool
    folder: Optional[str] = None
    document: Optional[str] = None
    expected_page_urls: list[str] = Field(default_factory=list)
    expected_source_types: list[str] = Field(default_factory=list)
    max_answer_length: Optional[int] = None
    follow_up_prompts: Optional[list[dict[str, Any]]] = None
    source_feedback_id: Optional[UUID] = None
    source_trace_id: Optional[UUID] = None
    tags: list[str]
    metadata: dict[str, Any]
    status: str = "active"
    status_note: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TestDatasetDetail(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    tags: list[str]
    test_count: int
    needs_work_count: int = 0
    created_at: datetime
    updated_at: datetime
    test_cases: list[TestCaseItem]

    model_config = {"from_attributes": True}


# --- Suggestion schema ---

class TestCaseSuggestion(BaseModel):
    feedback_id: UUID
    trace_id: Optional[UUID] = None
    feedback_value: float
    prompt: str
    actual_answer: Optional[str] = None
    suggested_expected_answer: Optional[str] = None
    context_filters: dict[str, str] = Field(default_factory=dict)
    team_filter: list[str] = Field(default_factory=list)
    tag_filter: list[str] = Field(default_factory=list)
    expected_sources: list[str] = Field(default_factory=list)
    message_count: Optional[int] = None
    has_summary: bool = False
    scored_at: Optional[datetime] = None
    comment: Optional[str] = None
    suggested_dataset_id: Optional[UUID] = None


# --- Export schema ---

class ExportTestCase(BaseModel):
    id: str
    prompt: str
    expectedAnswer: Optional[str] = None
    expectedSources: list[str] = Field(default_factory=list)
    teamFilter: list[str] = Field(default_factory=list)
    tagFilter: list[str] = Field(default_factory=list)
    filters: dict[str, str] = Field(default_factory=dict)
    folder: Optional[str] = None
    document: Optional[str] = None
    expectedPageUrls: list[str] = Field(default_factory=list)
    expectedSourceTypes: list[str] = Field(default_factory=list)
    maxAnswerLength: Optional[int] = None
    followUpPrompts: Optional[list[dict[str, Any]]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: Optional[str] = None
    statusNote: Optional[str] = None


class ExportResponse(BaseModel):
    name: str
    description: Optional[str] = None
    testCases: list[ExportTestCase]


# --- Import schema ---

class ImportRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    testCases: list[dict[str, Any]]
    filename: str = "import.json"
