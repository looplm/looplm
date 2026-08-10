"""Request/response shapes for synthetic question generation."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SyntheticQuestionRunRequest(BaseModel):
    """Start a generation run over one index provider.

    ``scope="partition"`` requires ``partition_key`` + ``partition_value`` and restricts the
    sample to that slice; ``corpus`` spreads it across the whole index. ``persist=False`` is the
    preview path: questions are generated and returned on the run, but no dataset, test case or
    label is written — the cheap way to tune the parameters before committing to a full run.
    """

    provider_id: UUID
    scope: str = Field(default="corpus", pattern="^(corpus|partition)$")
    partition_key: Optional[str] = Field(default=None, max_length=255)
    partition_value: Optional[str] = None
    # Chunks to sample. The upper bound is a cost guard: one LLM call covers several chunks, but
    # a 1000-chunk run is still a lot of tokens to spend without seeing a preview first.
    sample_size: int = Field(default=50, ge=1, le=1000)
    questions_per_chunk: int = Field(default=2, ge=1, le=5)
    # Percent of the run's questions that should be unanswerable. 0 disables negatives entirely.
    negative_share: int = Field(default=15, ge=0, le=50)
    verify_negatives: bool = True
    persist: bool = True
    # Append to this dataset instead of creating one. Ignored when persist is False.
    dataset_id: Optional[UUID] = None
    dataset_name: Optional[str] = Field(default=None, max_length=255)


class SyntheticQuestionRunCreateResponse(BaseModel):
    run_id: UUID
    status: str


class SyntheticQuestionItem(BaseModel):
    """One generated question and the chunk it is grounded in.

    ``source_chunk_id`` is the ground truth for the question. Negative questions have none —
    that is what makes them negative.
    """

    text: str
    style: str
    source_chunk_id: Optional[str] = None
    source_title: Optional[str] = None
    source_url: Optional[str] = None
    source_preview: Optional[str] = None


class SyntheticQuestionCounts(BaseModel):
    """What the run produced and what it discarded, so nothing is silently dropped."""

    chunks_sampled: int = 0
    chunks_used: int = 0
    # Quality flag slug -> chunks it disqualified (empty, tiny, mojibake, markup_heavy, duplicate).
    chunks_skipped: dict[str, int] = Field(default_factory=dict)
    questions_generated: int = 0
    duplicates_dropped: int = 0
    negatives_generated: int = 0
    negatives_dropped: int = 0
    cases_created: int = 0
    labels_created: int = 0


class SyntheticQuestionResults(BaseModel):
    questions: list[SyntheticQuestionItem] = Field(default_factory=list)
    counts: SyntheticQuestionCounts = Field(default_factory=SyntheticQuestionCounts)
    usage: Optional[dict] = None


class SyntheticQuestionRunSummary(BaseModel):
    """Row shape for the run list (no question bodies)."""

    id: UUID
    provider_id: UUID
    status: str
    stage: Optional[str] = None
    scope: str
    partition_key: Optional[str] = None
    partition_value: Optional[str] = None
    sample_size: int
    questions_per_chunk: int
    negative_share: int
    persist: bool
    dataset_id: Optional[UUID] = None
    dataset_name: Optional[str] = None
    total: int
    processed: int
    questions_generated: int = 0
    cases_created: int = 0
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class SyntheticQuestionRunSummaryListResponse(BaseModel):
    data: list[SyntheticQuestionRunSummary]


class SyntheticQuestionRunResponse(BaseModel):
    """Full run row, including the generated questions."""

    id: UUID
    provider_id: UUID
    status: str
    stage: Optional[str] = None
    error: Optional[str] = None
    scope: str
    partition_key: Optional[str] = None
    partition_value: Optional[str] = None
    sample_size: int
    questions_per_chunk: int
    negative_share: int
    verify_negatives: bool
    persist: bool
    dataset_id: Optional[UUID] = None
    dataset_name: Optional[str] = None
    total: int
    processed: int
    results: Optional[SyntheticQuestionResults] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
