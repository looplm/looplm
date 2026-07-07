"""Pydantic schemas for eval trigger and job endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

FilterMode = Literal["as_configured", "no_filters", "both"]


class TriggerEvalRequest(BaseModel):
    dataset_ids: list[UUID] | None = Field(None, description="Dataset IDs to evaluate. None = all datasets.")
    concurrency: int | None = Field(
        None,
        ge=1,
        le=10,
        description="Parallel test runners. Clamped server-side to settings.eval_max_concurrency to avoid throttling the target's shared embeddings deployment into keyword-only retrieval.",
    )
    filter_mode: FilterMode = Field(
        "as_configured",
        description=(
            "How to apply test case filters. "
            "'as_configured' = use filters from each test case (default), "
            "'no_filters' = ignore all filters (simulate new user), "
            "'both' = run each test case twice (with and without filters)"
        ),
    )
    max_turns: int | None = Field(
        None,
        ge=1,
        le=10,
        description="Max conversation turns for multi-turn test cases. Overrides project setting.",
    )
    use_batch: bool = Field(
        False,
        description="Use Azure OpenAI Batch API for LLM judge evaluators (50% cost, up to 24h).",
    )
    retrieval_only: bool = Field(
        False,
        description="Run only retrieval-focus evaluators (skip generation/LLM-judge evaluators).",
    )


RerunScope = Literal["failed", "filtered", "selected", "dlq"]


class RerunEvalRequest(BaseModel):
    test_ids: list[str] | None = Field(
        None,
        max_length=5000,
        description=(
            "Exact test_ids from the original run to rerun. "
            "'[filtered]'/'[unfiltered]' suffixes are stripped server-side."
        ),
    )
    scope: RerunScope | None = Field(
        None,
        description=(
            "If 'failed' and test_ids is omitted, the server reruns all failed results. "
            "If 'dlq', it reruns only the dead-letter rows (degraded/errored execution, "
            "not quality failures). Otherwise a label recorded in run metadata."
        ),
    )


class DatasetPickerItem(BaseModel):
    id: UUID
    name: str
    test_count: int
    needs_work_count: int = 0


class DatasetPickerResponse(BaseModel):
    datasets: list[DatasetPickerItem]


class EvalJobResponse(BaseModel):
    id: UUID
    project_id: UUID
    test_suite: str
    dataset_ids: list[UUID] | None = None
    status: str
    run_id: Optional[UUID] = None
    batch_eval_job_id: Optional[UUID] = None
    error: Optional[str] = None
    log: Optional[str] = None
    config: dict = {}
    progress_current: Optional[int] = None
    progress_total: Optional[int] = None
    started_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class EvalJobListResponse(BaseModel):
    data: list[EvalJobResponse]


class TriggerEvalResponse(BaseModel):
    job_id: UUID
    status: str


# --- Session schemas ---

class TriggerSessionRequest(BaseModel):
    dataset_ids: list[UUID] | None = Field(None, description="Dataset IDs to evaluate. None = all datasets.")
    experiment_ids: list[UUID] = Field(..., min_length=1, description="Experiment IDs to run.")
    concurrency: int | None = Field(
        None,
        ge=1,
        le=10,
        description="Parallel test runners per experiment. Clamped server-side to settings.eval_max_concurrency to avoid throttling the target's shared embeddings deployment into keyword-only retrieval.",
    )
    max_turns: int | None = Field(
        None,
        ge=1,
        le=10,
        description="Max conversation turns for multi-turn test cases.",
    )
    use_batch: bool = Field(
        False,
        description="Use Azure OpenAI Batch API for LLM judge evaluators (50% cost, up to 24h).",
    )


class TriggerSessionResponse(BaseModel):
    session_id: UUID
    experiment_count: int
    status: str


class EvalSessionResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    status: str
    dataset_ids: list[str] | None = None
    experiment_ids: list[str]
    config: dict = {}
    progress_current: Optional[int] = None
    progress_total: Optional[int] = None
    run_ids: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class EvalSessionListResponse(BaseModel):
    data: list[EvalSessionResponse]
