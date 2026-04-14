/**
 * Type definitions for LLM cost tracking.
 */

export interface ServiceCostBreakdown {
  service_name: string;
  cost_usd: number;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
}

export interface ModelCostBreakdown {
  model: string;
  provider: string;
  cost_usd: number;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
}

export interface CostSummaryResponse {
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_requests: number;
  by_service: ServiceCostBreakdown[];
  by_model: ModelCostBreakdown[];
}

export interface CostTrendPoint {
  date: string;
  cost_usd: number;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
}

export interface CostTrendResponse {
  points: CostTrendPoint[];
}

export interface CostDetailItem {
  id: string;
  service_name: string;
  function_name: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number | null;
  duration_ms: number | null;
  created_at: string;
}

export interface CostDetailsResponse {
  items: CostDetailItem[];
  total: number;
}

// Combined cost overview types

export interface CostOverviewTrendPoint {
  date: string;
  app_cost_usd: number;
  platform_cost_usd: number;
  total_cost_usd: number;
  app_requests: number;
  platform_requests: number;
}

export interface ModelCostItem {
  model: string;
  provider: string;
  cost_usd: number;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
}

export interface ServiceDetailItem {
  function_name: string;
  model: string;
  provider: string;
  cost_usd: number;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
}

export interface ServiceCostItem {
  service_name: string;
  cost_usd: number;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
  by_detail?: ServiceDetailItem[];
}

export interface CostsOverviewResponse {
  total_cost_usd: number;
  app_cost_usd: number;
  platform_cost_usd: number;
  total_app_tokens: number;
  total_platform_tokens: number;
  total_app_requests: number;
  total_platform_requests: number;
  trend: CostOverviewTrendPoint[];
  app_by_model: ModelCostItem[];
  platform_by_service: ServiceCostItem[];
  platform_by_model: ModelCostItem[];
}
