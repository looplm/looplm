"""Schemas for LLM cost tracking endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ServiceCostBreakdown(BaseModel):
    service_name: str
    cost_usd: float
    request_count: int
    input_tokens: int
    output_tokens: int


class ModelCostBreakdown(BaseModel):
    model: str
    provider: str
    cost_usd: float
    request_count: int
    input_tokens: int
    output_tokens: int


class CostSummaryResponse(BaseModel):
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    total_requests: int
    by_service: list[ServiceCostBreakdown]
    by_model: list[ModelCostBreakdown]


class CostTrendPoint(BaseModel):
    date: str
    cost_usd: float
    request_count: int
    input_tokens: int
    output_tokens: int


class CostTrendResponse(BaseModel):
    points: list[CostTrendPoint]


class CostDetailItem(BaseModel):
    id: UUID
    service_name: str
    function_name: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float | None
    duration_ms: int | None
    created_at: datetime


class CostDetailsResponse(BaseModel):
    items: list[CostDetailItem]
    total: int
