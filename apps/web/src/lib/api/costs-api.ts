/**
 * API client functions for LLM cost tracking.
 */

import type {
  CostSummaryResponse,
  CostTrendResponse,
  CostDetailsResponse,
  CostsOverviewResponse,
} from "../api-types/costs";
import { request } from "./client";

function qs(params?: Record<string, string>): string {
  if (!params) return "";
  const filtered = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== "")
  );
  const s = new URLSearchParams(filtered).toString();
  return s ? `?${s}` : "";
}

export const getCostSummary = (params?: Record<string, string>) =>
  request<CostSummaryResponse>(`/api/llm-costs/summary${qs(params)}`);

export const getCostTrend = (params?: Record<string, string>) =>
  request<CostTrendResponse>(`/api/llm-costs/trend${qs(params)}`);

export const getCostDetails = (params?: Record<string, string>) =>
  request<CostDetailsResponse>(`/api/llm-costs/details${qs(params)}`);

export const getCostsOverview = (params?: Record<string, string>) =>
  request<CostsOverviewResponse>(`/api/costs/overview${qs(params)}`);
