"""Schemas for the combined cost overview endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class ModelCostItem(BaseModel):
    model: str
    provider: str
    cost_usd: float
    request_count: int
    input_tokens: int
    output_tokens: int


class ServiceDetailItem(BaseModel):
    function_name: str
    model: str
    provider: str
    cost_usd: float
    request_count: int
    input_tokens: int
    output_tokens: int


class ServiceCostItem(BaseModel):
    service_name: str
    cost_usd: float
    request_count: int
    input_tokens: int
    output_tokens: int
    by_detail: list[ServiceDetailItem] = []


class CostOverviewTrendPoint(BaseModel):
    date: str
    app_cost_usd: float
    platform_cost_usd: float
    total_cost_usd: float
    app_requests: int
    platform_requests: int


class CostsOverviewResponse(BaseModel):
    total_cost_usd: float
    app_cost_usd: float
    platform_cost_usd: float
    total_app_tokens: int
    total_platform_tokens: int
    total_app_requests: int
    total_platform_requests: int

    trend: list[CostOverviewTrendPoint]

    app_by_model: list[ModelCostItem]
    platform_by_service: list[ServiceCostItem]
    platform_by_model: list[ModelCostItem]
