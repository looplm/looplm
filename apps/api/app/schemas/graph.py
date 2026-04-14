"""Pydantic schemas for aggregate graph endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AggregateGraphNode(BaseModel):
    id: str  # "{name}::{run_type}"
    name: str
    run_type: str | None = None
    execution_count: int = 0
    avg_duration_ms: float | None = None
    failure_count: int = 0
    success_count: int = 0


class AggregateGraphEdge(BaseModel):
    source: str  # parent node id
    target: str  # child node id
    weight: int = 1  # frequency of this path


class AggregateGraphResponse(BaseModel):
    nodes: list[AggregateGraphNode] = Field(default_factory=list)
    edges: list[AggregateGraphEdge] = Field(default_factory=list)
    total_traces_analyzed: int = 0
    root_node_ids: list[str] = Field(default_factory=list)
