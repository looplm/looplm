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
    cluster_path: list[str] = Field(default_factory=list)
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


# ── GitHub extraction ─────────────────────────────────────────

class ExtractedPrompt(BaseModel):
    """A single prompt the agent located in the connected codebase."""

    name: str = Field(description="Short, human-readable name for the prompt")
    template: str = Field(description="The prompt text / template, verbatim")
    variables: list[str] = Field(
        default_factory=list,
        description="Names of template placeholders (e.g. {topic} -> 'topic')",
    )
    file_path: str = Field(description="Repo-relative path the prompt was found in")
    line_start: int | None = Field(
        default=None, description="1-based line where the prompt begins, if known"
    )
    role: str | None = Field(
        default=None, description="system | user | assistant | tool, if discernible"
    )


class PromptLocation(BaseModel):
    """A pointer to a prompt found during the discovery pass (no template text)."""

    name: str = Field(description="Short, human-readable name for the prompt")
    file_path: str = Field(description="Repo-relative path the prompt lives in")
    line_start: int | None = Field(
        default=None, description="1-based line where the prompt begins, if known"
    )
    role: str | None = Field(
        default=None, description="system | user | assistant | tool, if discernible"
    )
    note: str | None = Field(
        default=None, description="One short phrase on what this prompt is for"
    )


class PromptLocationList(BaseModel):
    """Output of the discovery pass: where prompts live, not their contents."""

    summary: str = Field(default="", description="One-paragraph summary of what was found")
    locations: list[PromptLocation] = Field(default_factory=list)


class PromptRecheckResult(BaseModel):
    """Result of re-extracting a single prompt from the connected repo."""

    prompt: PromptOut
    changed: bool = False


class PlannedLocation(BaseModel):
    """A discovered prompt location shown in the pre-import selection step."""

    external_id: str
    name: str
    file_path: str
    line_start: int | None = None
    role: str | None = None
    note: str | None = None
    already_saved: bool = False


class PromptExtractionResponse(BaseModel):
    """Status of a background extraction run (polled by the frontend)."""

    id: str
    status: str
    error: str | None = None
    summary: str | None = None
    files_analyzed: list[str] = Field(default_factory=list)
    extracted_count: int = 0
    total_cost_usd: float | None = None
    num_turns: int | None = None
    progress_message: str | None = None
    progress_log: list[dict] = Field(default_factory=list)
    planned_locations: list[PlannedLocation] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── Selection / clustering / exclusion ────────────────────────

class ConfirmExtractionRequest(BaseModel):
    extraction_id: str
    selected_external_ids: list[str] = Field(default_factory=list)


class ClusterUpdateRequest(BaseModel):
    cluster_path: list[str] = Field(default_factory=list)


class ClusterMoveRequest(BaseModel):
    from_path: list[str]
    to_path: list[str]


class ClusterMoveResult(BaseModel):
    moved: int = 0


class ExclusionItem(BaseModel):
    external_id: str
    name: str = ""


class ExclusionListResponse(BaseModel):
    data: list[ExclusionItem] = Field(default_factory=list)
    total: int = 0


class RemoveExclusionRequest(BaseModel):
    external_id: str
