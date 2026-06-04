/**
 * Analytics API — request-type clustering + data-retrieval insights.
 */

import { request } from "./client";
import type {
  RequestClustersResponse,
  RetrievalActivityPoint,
  RetrievalSource,
} from "../api-types/analytics";

export interface AnalyticsFilters {
  from_date?: string;
  to_date?: string;
  environment?: string;
  include_user_ids?: string[];
  exclude_user_ids?: string[];
}

export const analyzeRequestClusters = (body: AnalyticsFilters & { limit?: number }) =>
  request<{ analysis_id: string; status: string }>("/api/analytics/request-clusters", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getRequestClusters = (analysisId: string) =>
  request<RequestClustersResponse>(`/api/analytics/request-clusters/${analysisId}`);

export const getLatestRequestClusters = () =>
  request<RequestClustersResponse>("/api/analytics/request-clusters/latest");

export const stopRequestClusters = (analysisId: string) =>
  request<{ message: string; status: string }>(
    `/api/analytics/request-clusters/${analysisId}/stop`,
    { method: "POST" },
  );

function buildQuery(filters: AnalyticsFilters, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams(extra);
  if (filters.from_date) params.set("from_date", filters.from_date);
  if (filters.to_date) params.set("to_date", filters.to_date);
  if (filters.environment) params.set("environment", filters.environment);
  for (const id of filters.include_user_ids ?? []) params.append("include_user_ids", id);
  for (const id of filters.exclude_user_ids ?? []) params.append("exclude_user_ids", id);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export const getRetrievalSources = (filters: AnalyticsFilters, limit = 20) =>
  request<RetrievalSource[]>(
    `/api/analytics/retrieval/sources${buildQuery(filters, { limit: String(limit) })}`,
  );

export const getRetrievalActivity = (filters: AnalyticsFilters) =>
  request<RetrievalActivityPoint[]>(
    `/api/analytics/retrieval/activity${buildQuery(filters)}`,
  );
