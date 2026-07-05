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


# --- Files tab: file-type overview + filename search → chunks-of-a-file ---


class IndexFileTypeValue(BaseModel):
    """One file/content type present in the index, with its chunk count."""

    value: str
    count: int


class IndexFileTypesResponse(BaseModel):
    """The detected file-type dimension and its value distribution.

    ``field`` is ``None`` when the index exposes no suitable facetable type field —
    the UI then hides the section.
    """

    field: Optional[str] = None
    values: list[IndexFileTypeValue] = Field(default_factory=list)


class IndexFileMatch(BaseModel):
    """A distinct file surfaced by a filename/title search.

    ``key``/``value`` are the backend field and value to filter its chunks on;
    ``kind`` is ``attachment`` or ``page``.
    """

    key: str
    value: str
    label: str
    kind: Literal["attachment", "page", "web"]
    chunk_count: int
    url: Optional[str] = None


class IndexFileListResponse(BaseModel):
    data: list[IndexFileMatch] = Field(default_factory=list)


class IndexFileChunk(BaseModel):
    """One chunk of a file, in reading order."""

    id: str
    index: int  # 0-based position in the returned (ordered) list
    ordinal: Optional[str] = None  # raw value of the index's ordinal field, if any
    title: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None


class IndexFileChunksResponse(BaseModel):
    """Every chunk of one file, ordered. ``ordinal_available`` is False when the
    index has no ordinal field, so chunks are in index order rather than reading
    order."""

    label: str
    ordinal_available: bool
    documents: list[IndexFileChunk] = Field(default_factory=list)


class IndexChunkMetadataResponse(BaseModel):
    """All index fields for one chunk (embedding vectors omitted).

    ``found`` is False when the id is not in the index. Powers the per-chunk
    "metadata" toggle on the Files tab.
    """

    id: str
    found: bool
    fields: dict[str, Any] = Field(default_factory=dict)


# --- Fields tab: index schema (attributes + example values) + LLM field docs ---


class IndexFieldSchemaItem(BaseModel):
    """One field of the index schema, with capability flags and example values.

    ``type`` is the backend-native type (e.g. ``Edm.String``,
    ``Collection(Edm.String)``). The boolean flags are Azure's field attributes.
    ``example_values`` are a few distinct non-empty sampled values;
    ``fill_rate`` is the fraction of the sample carrying any value (0..1).
    """

    name: str
    type: str
    is_key: bool = False
    is_collection: bool = False
    is_vector: bool = False
    searchable: bool = False
    filterable: bool = False
    facetable: bool = False
    sortable: bool = False
    retrievable: bool = True
    example_values: list[str] = Field(default_factory=list)
    fill_rate: float = 0.0


class IndexFieldSchemaResponse(BaseModel):
    """The index's field schema plus the sample size the examples came from."""

    fields: list[IndexFieldSchemaItem] = Field(default_factory=list)
    sample_size: int = 0


class IndexFieldDoc(BaseModel):
    """LLM-written explanation of one field: what it is for."""

    name: str
    purpose: str


class IndexFieldGroup(BaseModel):
    """A cluster of related/confusable fields with the distinction between them.

    ``field_names`` are the fields in the cluster; ``distinction`` explains how
    they differ from one another (e.g. ``page_url`` vs ``attachment_url``).
    """

    title: str
    field_names: list[str] = Field(default_factory=list)
    distinction: str


class IndexFieldDocs(BaseModel):
    """The LLM's per-field explanations and groups of confusable fields."""

    summary: str = ""
    fields: list[IndexFieldDoc] = Field(default_factory=list)
    groups: list[IndexFieldGroup] = Field(default_factory=list)


class IndexFieldDocsResponse(BaseModel):
    """Cached or freshly-computed field documentation for a provider."""

    docs: Optional[IndexFieldDocs] = None
    generated_at: Optional[datetime] = None
    model: Optional[str] = None


class IndexFieldDocsRequest(BaseModel):
    provider_id: UUID


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
