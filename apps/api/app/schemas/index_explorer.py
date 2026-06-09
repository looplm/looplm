"""Pydantic schemas for the read-only index-explorer (Data Sources page).

The explorer reads a connected retrieval index and exposes it as a lazy,
hierarchical tree: pick an ordered list of fields to group by, drill down level
by level, and finally into sampled documents. It reuses the same
``BaseIndexProvider`` introspection that powers RAG coverage — see
``app/index_providers/base.py``.
"""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


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
    has_children: bool  # True when further group_by keys remain below this node


class IndexTreeDocument(BaseModel):
    """A sampled document leaf."""

    id: str
    title: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None


class IndexTreeResponse(BaseModel):
    """One lazily-expanded level of the tree.

    ``level == "group"`` → ``groups`` holds the next grouping field's values.
    ``level == "documents"`` → ``documents`` holds sampled docs for the leaf
    (``parent_doc_count`` is the value's total, so the UI can show "N of M").
    """

    level: Literal["group", "documents"]
    key: Optional[str] = None  # the field whose distribution ``groups`` represents
    groups: list[IndexTreeGroupNode] = Field(default_factory=list)
    documents: list[IndexTreeDocument] = Field(default_factory=list)
    parent_doc_count: Optional[int] = None
