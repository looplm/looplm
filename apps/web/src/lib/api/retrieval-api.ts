/**
 * Retrieval API — the aggregate retrieval pipeline flow chart.
 */

import { request } from "./client";
import type { AnalyticsFilters } from "./analytics-api";
import type {
  RetrievalPipelineResponse,
  RetrievalRunMetrics,
} from "../api-types/retrieval";

function buildQuery(filters: AnalyticsFilters): string {
  const params = new URLSearchParams();
  if (filters.from_date) params.set("from_date", filters.from_date);
  if (filters.to_date) params.set("to_date", filters.to_date);
  if (filters.environment) params.set("environment", filters.environment);
  for (const id of filters.include_user_ids ?? []) params.append("include_user_ids", id);
  for (const id of filters.exclude_user_ids ?? []) params.append("exclude_user_ids", id);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export const getRetrievalPipeline = (filters: AnalyticsFilters = {}) =>
  request<RetrievalPipelineResponse>(`/api/pipeline/graph${buildQuery(filters)}`);

export const getRetrievalMetrics = (runId?: string) =>
  request<RetrievalRunMetrics>(
    `/api/pipeline/retrieval-metrics${runId ? `?run_id=${encodeURIComponent(runId)}` : ""}`,
  );
