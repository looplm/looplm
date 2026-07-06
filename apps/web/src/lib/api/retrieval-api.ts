/**
 * Retrieval API — the aggregate retrieval pipeline flow chart.
 */

import { ApiError, request } from "./client";
import type { AnalyticsFilters } from "./analytics-api";
import type {
  RetrievalPipelineResponse,
  RetrievalRunMetrics,
  RetrievalTargets,
  ByStageMetricsResponse,
  CaseDiagnosisResponse,
  LabelingRunResponse,
  LabelingPoolResponse,
  ChunkLabelUpsert,
  ChunkMetadataResponse,
  AgreementReport,
  AiJudgeResponse,
  AiJudgePreviewResponse,
  PlanQueriesResponse,
  LabelingPromptDefaults,
  RetrievalRunSummary,
  RetrievalRunRecord,
  RetrievalRunCreateBody,
  RetrievalRunMetadataUpdate,
  RetrievalComputeStartBody,
  RetrievalComputeJob,
  RetrievalReadiness,
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

// Is the project configured to measure retrieval quality (embedding model + index semantic config)?
// Drives the readiness banner on the Retrieval/Labeling pages. The embed probe is cached server-side.
export const getRetrievalReadiness = (opts: { refresh?: boolean } = {}, signal?: AbortSignal) =>
  request<RetrievalReadiness>(
    `/api/pipeline/retrieval-readiness${opts.refresh ? "?refresh=true" : ""}`,
    { signal },
  );

export const getRetrievalMetrics = (
  opts: {
    runId?: string;
    datasetId?: string;
    datasetIds?: string[];
    source?: "urls" | "labels";
    refresh?: boolean;
    goldSource?: "human" | "ai" | "both";
    minGrade?: number;
  } = {},
  signal?: AbortSignal,
) => {
  const params = new URLSearchParams({ source: opts.source ?? "urls" });
  if (opts.runId) params.set("run_id", opts.runId);
  if (opts.datasetId) params.set("dataset_id", opts.datasetId);
  for (const id of opts.datasetIds ?? []) params.append("dataset_ids", id);
  if (opts.refresh) params.set("refresh", "true");
  if (opts.goldSource && opts.goldSource !== "human") params.set("gold_source", opts.goldSource);
  if (opts.minGrade && opts.minGrade !== 1) params.set("min_grade", String(opts.minGrade));
  return request<RetrievalRunMetrics>(`/api/pipeline/retrieval-metrics?${params.toString()}`, {
    signal,
  });
};

// Per-stage deterministic retrieval metrics (sparse/dense/RRF/reranked/agentic) vs chunk-label gold.
export const getRetrievalByStageMetrics = (
  opts: {
    datasetIds?: string[];
    goldSource?: "human" | "ai" | "both";
    minGrade?: number;
    refresh?: boolean;
  } = {},
  signal?: AbortSignal,
) => {
  const params = new URLSearchParams();
  for (const id of opts.datasetIds ?? []) params.append("dataset_ids", id);
  if (opts.goldSource && opts.goldSource !== "human") params.set("gold_source", opts.goldSource);
  if (opts.minGrade && opts.minGrade !== 1) params.set("min_grade", String(opts.minGrade));
  if (opts.refresh) params.set("refresh", "true");
  const qs = params.toString();
  return request<ByStageMetricsResponse>(
    `/api/pipeline/retrieval-metrics/by-stage${qs ? `?${qs}` : ""}`,
    { signal },
  );
};

// Per-case retrieval diagnosis: which judged-relevant chunks a retriever missed, and why
// (not_in_index / missing_embedding / bad_chunk / buried / unretrievable).
export const getCaseDiagnosis = (
  opts: {
    testId: string;
    k?: number;
    retriever?: string;
    goldSource?: "human" | "ai" | "both";
    minGrade?: number;
    refresh?: boolean;
  },
  signal?: AbortSignal,
) => {
  const params = new URLSearchParams({ test_id: opts.testId });
  if (opts.k) params.set("k", String(opts.k));
  if (opts.retriever) params.set("retriever", opts.retriever);
  if (opts.goldSource && opts.goldSource !== "human") params.set("gold_source", opts.goldSource);
  if (opts.minGrade && opts.minGrade !== 1) params.set("min_grade", String(opts.minGrade));
  if (opts.refresh) params.set("refresh", "true");
  return request<CaseDiagnosisResponse>(
    `/api/pipeline/case-diagnosis?${params.toString()}`,
    { signal },
  );
};

// --- Detached metrics compute (fire-and-poll) ---

// Start a labels-path metrics compute as a background job. Returns the job to poll; the result
// lands in the server cache, read back via getRetrievalMetrics / getRetrievalByStageMetrics.
export const startRetrievalCompute = (body: RetrievalComputeStartBody, signal?: AbortSignal) =>
  request<RetrievalComputeJob>(`/api/pipeline/retrieval-metrics/compute`, {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });

export const getRetrievalComputeJob = (jobId: string, signal?: AbortSignal) =>
  request<RetrievalComputeJob>(`/api/pipeline/retrieval-metrics/compute/${jobId}`, { signal });

// Poll a compute job until it settles. Resolves on completion; on failure throws an ApiError
// carrying the server error + traceback (debug) so the caller can render + copy it. Aborting the
// signal rejects with an AbortError. Short HTTP calls only — a reload/timeout can't wedge this.
export const pollRetrievalCompute = async (
  jobId: string,
  signal: AbortSignal,
  intervalMs = 1500,
): Promise<void> => {
  for (;;) {
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    const job = await getRetrievalComputeJob(jobId, signal);
    if (job.status === "completed") return;
    if (job.status === "failed") {
      throw new ApiError({
        code: "COMPUTE_FAILED",
        message: job.error || "Compute failed",
        status: 500,
        method: "POST",
        path: "/api/pipeline/retrieval-metrics/compute",
        trace: job.trace ?? undefined,
      });
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
};

// --- Saved retrieval runs (durable history) ---

export const createRetrievalRun = (body: RetrievalRunCreateBody, signal?: AbortSignal) =>
  request<RetrievalRunRecord>(`/api/pipeline/retrieval-runs`, {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });

export const listRetrievalRuns = (signal?: AbortSignal) =>
  request<{ data: RetrievalRunSummary[] }>(`/api/pipeline/retrieval-runs`, { signal });

export const getRetrievalRun = (runId: string, signal?: AbortSignal) =>
  request<RetrievalRunRecord>(`/api/pipeline/retrieval-runs/${runId}`, { signal });

export const updateRetrievalRunMeta = (runId: string, meta: RetrievalRunMetadataUpdate) =>
  request<RetrievalRunRecord>(`/api/pipeline/retrieval-runs/${runId}`, {
    method: "PATCH",
    body: JSON.stringify(meta),
  });

export const deleteRetrievalRun = (runId: string) =>
  request<{ deleted: boolean }>(`/api/pipeline/retrieval-runs/${runId}`, { method: "DELETE" });

export const bulkDeleteRetrievalRuns = (runIds: string[]) =>
  request<{ deleted: number }>(`/api/pipeline/retrieval-runs/bulk-delete`, {
    method: "POST",
    body: JSON.stringify({ run_ids: runIds }),
  });

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
  opts: {
    datasetId?: string;
    instructions?: string;
    includeExpectedAnswer?: boolean;
    refresh?: boolean;
    signal?: AbortSignal;
  } = {},
) =>
  request<AiJudgeResponse>(`/api/pipeline/labeling/ai-judge`, {
    method: "POST",
    signal: opts.signal,
    body: JSON.stringify({
      test_id: testId,
      dataset_id: opts.datasetId,
      instructions: opts.instructions,
      // Omit when true so the request matches the server default (include).
      include_expected_answer: opts.includeExpectedAnswer === false ? false : undefined,
      // Re-query the index before grading; omit when false to match the server default (cached).
      refresh: opts.refresh === true ? true : undefined,
    }),
  });

// The exact prompt the AI judge would send for a case (system + user, with chunk text folded in),
// rendered server-side so the preview never drifts from what actually runs. No LLM call.
export const aiJudgePreviewCase = (
  testId: string,
  opts: { datasetId?: string; instructions?: string; includeExpectedAnswer?: boolean } = {},
) =>
  request<AiJudgePreviewResponse>(`/api/pipeline/labeling/ai-judge/preview`, {
    method: "POST",
    body: JSON.stringify({
      test_id: testId,
      dataset_id: opts.datasetId,
      instructions: opts.instructions,
      include_expected_answer: opts.includeExpectedAnswer === false ? false : undefined,
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
