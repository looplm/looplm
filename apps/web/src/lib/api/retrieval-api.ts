/**
 * Retrieval API — the aggregate retrieval pipeline flow chart.
 */

import { request } from "./client";
import type { AnalyticsFilters } from "./analytics-api";
import type {
  RetrievalPipelineResponse,
  RetrievalRunMetrics,
  RetrievalTargets,
  LabelingRunResponse,
  ChunkLabelUpsert,
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

export const getRetrievalMetrics = (runId?: string, source: "urls" | "labels" = "urls") => {
  const params = new URLSearchParams({ source });
  if (runId) params.set("run_id", runId);
  return request<RetrievalRunMetrics>(`/api/pipeline/retrieval-metrics?${params.toString()}`);
};

export const getLabelingView = (runId?: string) =>
  request<LabelingRunResponse>(
    `/api/pipeline/labeling${runId ? `?run_id=${encodeURIComponent(runId)}` : ""}`,
  );

export const saveChunkLabels = (labels: ChunkLabelUpsert[]) =>
  request<{ saved: number }>(`/api/pipeline/labels`, {
    method: "POST",
    body: JSON.stringify({ labels }),
  });

export const setLabelingComplete = (testId: string, complete: boolean) =>
  request<{ test_id: string; complete: boolean }>(`/api/pipeline/labeling/status`, {
    method: "PUT",
    body: JSON.stringify({ test_id: testId, complete }),
  });

export const getRetrievalTargets = () =>
  request<RetrievalTargets>(`/api/pipeline/targets`);

export const saveRetrievalTargets = (targets: RetrievalTargets) =>
  request<RetrievalTargets>(`/api/pipeline/targets`, {
    method: "PUT",
    body: JSON.stringify(targets),
  });
