"""Pydantic schemas for route frequency analysis."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RouteNode(BaseModel):
    id: str
    name: str
    run_type: str | None = None
    call_count: int = 0
    avg_latency_ms: float | None = None
    error_rate: float = 0.0
    total_duration_ms: float = 0.0


class RouteEdge(BaseModel):
    source: str
    target: str
    frequency: int = 1
    weight: float | None = None
    percentage: float | None = None
    avg_latency_ms: float | None = None


class BottleneckNode(BaseModel):
    node_id: str
    name: str
    run_type: str | None = None
    call_count: int = 0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    bottleneck_score: float = 0.0
    reason: str = ""


class RouteAnalysisResponse(BaseModel):
    nodes: list[RouteNode] = Field(default_factory=list)
    edges: list[RouteEdge] = Field(default_factory=list)
    total_traces: int = 0
    root_node_ids: list[str] = Field(default_factory=list)


class BottleneckResponse(BaseModel):
    bottlenecks: list[BottleneckNode] = Field(default_factory=list)
    total_traces: int = 0
