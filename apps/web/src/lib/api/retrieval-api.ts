/**
 * Retrieval API — the aggregate retrieval pipeline flow chart.
 */

import { request } from "./client";
import type { AnalyticsFilters } from "./analytics-api";
import type {
  RetrievalPipelineResponse,
  RetrievalRunMetrics,
  RetrievalTargets,
  ByStageMetricsResponse,
  LabelingRunResponse,
  LabelingPoolResponse,
  ChunkLabelUpsert,
  ChunkMetadataResponse,
  AgreementReport,
  AiJudgeResponse,
  AiJudgePreviewResponse,
  PlanQueriesResponse,
  LabelingPromptDefaults,
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

export const getRetrievalMetrics = (
  opts: {
    runId?: string;
    datasetId?: string;
    datasetIds?: string[];
    source?: "urls" | "labels";
    refresh?: boolean;
    goldSource?: "human" | "ai" | "both";
  } = {},
  signal?: AbortSignal,
) => {
  const params = new URLSearchParams({ source: opts.source ?? "urls" });
  if (opts.runId) params.set("run_id", opts.runId);
  if (opts.datasetId) params.set("dataset_id", opts.datasetId);
  for (const id of opts.datasetIds ?? []) params.append("dataset_ids", id);
  if (opts.refresh) params.set("refresh", "true");
  if (opts.goldSource && opts.goldSource !== "human") params.set("gold_source", opts.goldSource);
  return request<RetrievalRunMetrics>(`/api/pipeline/retrieval-metrics?${params.toString()}`, {
    signal,
  });
};

// Per-stage deterministic retrieval metrics (sparse/dense/RRF/reranked/agentic) vs chunk-label gold.
export const getRetrievalByStageMetrics = (
  opts: { datasetIds?: string[]; goldSource?: "human" | "ai" | "both"; refresh?: boolean } = {},
  signal?: AbortSignal,
) => {
  const params = new URLSearchParams();
  for (const id of opts.datasetIds ?? []) params.append("dataset_ids", id);
  if (opts.goldSource && opts.goldSource !== "human") params.set("gold_source", opts.goldSource);
  if (opts.refresh) params.set("refresh", "true");
  const qs = params.toString();
  return request<ByStageMetricsResponse>(
    `/api/pipeline/retrieval-metrics/by-stage${qs ? `?${qs}` : ""}`,
    { signal },
  );
};

export const getLabelingView = (datasetId?: string) =>
  request<LabelingRunResponse>(
    `/api/pipeline/labeling${datasetId ? `?dataset_id=${encodeURIComponent(datasetId)}` : ""}`,
  );

export const getLabelingPool = (
  testId: string,
  opts: { datasetId?: string; q?: string; depth?: number; refresh?: boolean } = {},
) => {
  const params = new URLSearchParams({ test_id: testId });
  if (opts.datasetId) params.set("dataset_id", opts.datasetId);
  if (opts.q) params.set("q", opts.q);
  if (opts.depth) params.set("depth", String(opts.depth));
  if (opts.refresh) params.set("refresh", "true");
  return request<LabelingPoolResponse>(`/api/pipeline/labeling/pool?${params.toString()}`);
};

export const saveChunkLabels = (labels: ChunkLabelUpsert[]) =>
  request<{ saved: number }>(`/api/pipeline/labels`, {
    method: "POST",
    body: JSON.stringify({ labels }),
  });

export const deleteChunkLabel = (testId: string, chunkId: string) => {
  const params = new URLSearchParams({ test_id: testId, chunk_id: chunkId });
  return request<{ deleted: boolean }>(`/api/pipeline/labels?${params.toString()}`, {
    method: "DELETE",
  });
};

export const aiJudgeCase = (
  testId: string,
  opts: { datasetId?: string; instructions?: string } = {},
) =>
  request<AiJudgeResponse>(`/api/pipeline/labeling/ai-judge`, {
    method: "POST",
    body: JSON.stringify({
      test_id: testId,
      dataset_id: opts.datasetId,
      instructions: opts.instructions,
    }),
  });

// The exact prompt the AI judge would send for a case (system + user, with chunk text folded in),
// rendered server-side so the preview never drifts from what actually runs. No LLM call.
export const aiJudgePreviewCase = (
  testId: string,
  opts: { datasetId?: string; instructions?: string } = {},
) =>
  request<AiJudgePreviewResponse>(`/api/pipeline/labeling/ai-judge/preview`, {
    method: "POST",
    body: JSON.stringify({
      test_id: testId,
      dataset_id: opts.datasetId,
      instructions: opts.instructions,
    }),
  });

// Plan agentic sub-queries for a case with the LLM and persist them; later pools fold them in.
export const planCaseQueries = (
  testId: string,
  opts: { datasetId?: string; instructions?: string; maxQueries?: number } = {},
) =>
  request<PlanQueriesResponse>(`/api/pipeline/labeling/plan-queries`, {
    method: "POST",
    body: JSON.stringify({
      test_id: testId,
      dataset_id: opts.datasetId,
      instructions: opts.instructions,
      max_queries: opts.maxQueries,
    }),
  });

// Default rubrics for the AI judge and query planner (shown + editable in the labeling UI).
export const getLabelingPrompts = () =>
  request<LabelingPromptDefaults>(`/api/pipeline/labeling/prompts`);

export const setLabelingComplete = (testId: string, complete: boolean) =>
  request<{ test_id: string; complete: boolean }>(`/api/pipeline/labeling/status`, {
    method: "PUT",
    body: JSON.stringify({ test_id: testId, complete }),
  });

export const setLabelingSlice = (testId: string, slice: string | null) =>
  request<{ test_id: string; slice: string | null }>(`/api/pipeline/labeling/slice`, {
    method: "PUT",
    body: JSON.stringify({ test_id: testId, slice }),
  });

export const getAgreement = () =>
  request<AgreementReport>(`/api/pipeline/labeling/agreement`);

export const setGold = (testId: string, chunkId: string, relevance: number) =>
  request<{ test_id: string; chunk_id: string; relevance: number }>(
    `/api/pipeline/labeling/gold`,
    { method: "PUT", body: JSON.stringify({ test_id: testId, chunk_id: chunkId, relevance }) },
  );

export const getChunkMetadata = (chunkId: string) =>
  request<ChunkMetadataResponse>(
    `/api/pipeline/chunk-metadata?chunk_id=${encodeURIComponent(chunkId)}`,
  );

export const getRetrievalTargets = () =>
  request<RetrievalTargets>(`/api/pipeline/targets`);

export const saveRetrievalTargets = (targets: RetrievalTargets) =>
  request<RetrievalTargets>(`/api/pipeline/targets`, {
    method: "PUT",
    body: JSON.stringify(targets),
  });
