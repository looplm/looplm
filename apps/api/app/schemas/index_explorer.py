"""Pydantic schemas for the read-only index-explorer (Data Sources page).

The explorer reads a connected retrieval index and exposes it as a lazy,
hierarchical tree: pick an ordered list of fields to group by, drill down level
by level, and finally into sampled documents. It reuses the same
``BaseIndexProvider`` introspection that powers RAG coverage — see
``app/index_providers/base.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class IndexProviderOption(BaseModel):
    """Minimal provider projection for the explorer's picker (read-only)."""

    id: UUID
    type: str
    name: str

    model_config = {"from_attributes": True}


class IndexProviderOptionListResponse(BaseModel):
    data: list[IndexProviderOption]


class IndexPartitionKey(BaseModel):
    key: str
    label: str
    multivalued: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class IndexSummaryResponse(BaseModel):
    """Headline numbers + the dimensions the corpus can be grouped by."""

    document_count: int
    partition_keys: list[IndexPartitionKey]


class IndexTreeGroupNode(BaseModel):
    """One value of the current grouping field, with its document count."""

    value: str
    doc_count: int
    has_children: bool  # True when further levels remain below this node


class IndexTreeSection(BaseModel):
    """One field's value distribution at the current level.

    A level normally has a single section. When the level groups several
    *parallel* fields (e.g. ``tags`` and ``team``), each is its own section so
    the UI can render them side by side instead of nested.
    """

    key: str  # the field whose distribution ``groups`` represents
    label: str
    groups: list[IndexTreeGroupNode] = Field(default_factory=list)


class IndexTreeDocument(BaseModel):
    """A sampled document leaf."""

    id: str
    title: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None


class IndexTreeResponse(BaseModel):
    """One lazily-expanded level of the tree.

    ``level == "group"`` → ``sections`` holds the next level's field
    distribution(s). ``level == "documents"`` → ``documents`` holds sampled
    docs for the leaf.
    """

    level: Literal["group", "documents"]
    sections: list[IndexTreeSection] = Field(default_factory=list)
    documents: list[IndexTreeDocument] = Field(default_factory=list)


# --- Grouping advisor: LLM-suggested hierarchy + metadata-quality hints ---


class GroupingLevel(BaseModel):
    """One level of the suggested hierarchy. ``keys`` holds the field(s) at this
    level; more than one means they are shown in parallel (side by side)."""

    keys: list[str] = Field(default_factory=list)
    reason: str = ""


class MetadataHint(BaseModel):
    """A metadata-quality observation surfaced to the user.

    ``field`` points at an existing partition key the hint is about;
    ``suggested_field`` names a *new* field the user should add to the index
    to enable better grouping (e.g. splitting a path-encoded field).
    """

    severity: Literal["info", "warning"]
    title: str
    message: str
    field: Optional[str] = None
    suggested_field: Optional[str] = None


class IndexGroupingSuggestion(BaseModel):
    """The advisor's recommended grouping for an index.

    ``suggested_levels`` is ordered top to bottom; each inner list is the
    field(s) at that level (more than one = parallel facets shown side by side).
    """

    suggested_levels: list[list[str]] = Field(default_factory=list)
    summary: str = ""
    levels: list[GroupingLevel] = Field(default_factory=list)
    hints: list[MetadataHint] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy(cls, data: Any) -> Any:
        """Read suggestions persisted before parallel levels existed.

        Old shape used a flat ``suggested_group_by`` and ``levels[].key`` —
        normalize both to the parallel-aware shape so cached rows still load.
        """
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if "suggested_levels" not in d and "suggested_group_by" in d:
            d["suggested_levels"] = [[k] for k in (d.get("suggested_group_by") or [])]
        lvls = d.get("levels")
        if isinstance(lvls, list):
            d["levels"] = [
                {**lvl, "keys": [lvl["key"]]}
                if isinstance(lvl, dict) and "keys" not in lvl and "key" in lvl
                else lvl
                for lvl in lvls
            ]
        return d


class IndexGroupingSuggestionResponse(BaseModel):
    """Cached or freshly-computed grouping suggestion for a provider."""

    suggestion: Optional[IndexGroupingSuggestion] = None
    suggested_at: Optional[datetime] = None
    model: Optional[str] = None


class IndexGroupingSuggestionRequest(BaseModel):
    provider_id: UUID
