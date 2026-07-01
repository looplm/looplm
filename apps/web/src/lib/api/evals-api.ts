/**
 * API functions for Evaluations, Eval Trigger, Eval Sessions, Reports,
 * Top Questions, Suggestions, and JSON Imports.
 */

import type {
  ClassifyFailuresResponse,
  EvalResultItem,
  EvalRunListResponse,
  EvalRunDetail,
  EvalRunListItem,
  EvalRunStats,
  DatasetPickerResponse,
  EvalJob,
  EvalJobListResponse,
  EvalJobLogsResponse,
  TriggerEvalResponse,
  TestCaseItem,
  TestCaseCreateBody,
  JsonImportListResponse,
  EvalReportResponse,
  EvalSession,
  EvalSessionListResponse,
  TriggerSessionResponse,
} from "../api-types";
import { request } from "./client";

// --- Evaluations ---

export const getEvalRuns = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<EvalRunListResponse>(`/api/evals${qs}`);
};

export const getEvalRun = (id: string) =>
  request<EvalRunDetail>(`/api/evals/${id}`);

export const getEvalResult = (runId: string, resultId: string) =>
  request<EvalResultItem>(`/api/evals/${runId}/results/${resultId}`);

export const getEvalRunStats = (id: string, excludeGraders?: string[]) => {
  const qs = excludeGraders?.length ? `?exclude_graders=${excludeGraders.join(",")}` : "";
  return request<EvalRunStats>(`/api/evals/${id}/stats${qs}`);
};

export const importEvalRun = (body: unknown) =>
  request<EvalRunListItem>("/api/evals/import", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const deleteEvalRun = (id: string) =>
  request<void>(`/api/evals/${id}`, { method: "DELETE" });

export const classifyEvalFailures = (id: string) =>
  request<ClassifyFailuresResponse>(`/api/evals/${id}/classify-failures`, {
    method: "POST",
  });

export const getEvalReport = (id: string) =>
  request<EvalReportResponse>(`/api/evals/${id}/report`);

export const generateMultiRunReport = (runIds: string[], relevanceFilter?: string[]) =>
  request<import("../api-types").MultiRunReportResponse>("/api/evals/report", {
    method: "POST",
    body: JSON.stringify({
      run_ids: runIds,
      ...(relevanceFilter ? { relevance_filter: relevanceFilter } : {}),
    }),
  });

export const bulkDeleteEvalRuns = (ids: string[]) =>
  Promise.all(ids.map((id) => deleteEvalRun(id)));

// --- Saved Reports ---

export const getEvalReports = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<import("../api-types").EvalReportListResponse>(`/api/evals/reports${qs}`);
};

export const getEvalReportById = (id: string) =>
  request<import("../api-types").EvalReportDetail>(`/api/evals/reports/${id}`);

export const deleteEvalReport = (id: string) =>
  request<void>(`/api/evals/reports/${id}`, { method: "DELETE" });

// --- Eval Trigger ---

export const getDatasetsPicker = () =>
  request<DatasetPickerResponse>("/api/evals/trigger/datasets");

export const triggerEval = (
  datasetIds?: string[],
  concurrency?: number,
  filterMode?: string,
  useBatch?: boolean,
  retrievalOnly?: boolean,
) =>
  request<TriggerEvalResponse>("/api/evals/trigger", {
    method: "POST",
    body: JSON.stringify({
      dataset_ids: datasetIds || null,
      concurrency,
      filter_mode: filterMode,
      use_batch: useBatch,
      retrieval_only: retrievalOnly,
    }),
  });

export type RerunScope = "failed" | "filtered" | "selected";

export const rerunEval = (runId: string, opts?: { testIds?: string[]; scope?: RerunScope }) =>
  request<TriggerEvalResponse>(`/api/evals/${runId}/rerun`, {
    method: "POST",
    ...(opts
      ? { body: JSON.stringify({ test_ids: opts.testIds ?? null, scope: opts.scope ?? null }) }
      : {}),
  });

export const getTestCaseHistory = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<import("../api-types").TestCaseHistoryResponse>(`/api/evals/test-case-history${qs}`);
};

export const getEvalJobs = (status?: string) => {
  const qs = status ? `?status=${status}` : "";
  return request<EvalJobListResponse>(`/api/evals/jobs${qs}`);
};

export const getEvalJob = (id: string) =>
  request<EvalJob>(`/api/evals/jobs/${id}`);

export const getEvalJobLogs = (id: string, offset = 0) =>
  request<EvalJobLogsResponse>(`/api/evals/jobs/${id}/logs?offset=${offset}`);

export const stopEvalJob = (id: string) =>
  request<{ message: string; job_id: string }>(`/api/evals/jobs/${id}/stop`, { method: "POST" });

export const restartEvalJob = (id: string) =>
  request<TriggerEvalResponse>(`/api/evals/jobs/${id}/restart`, { method: "POST" });

export const startAutoGrade = (integrationId: string) =>
  request<{ message: string }>(`/api/evals/auto-grade/${integrationId}/start`, {
    method: "POST",
  });

export const stopAutoGrade = (integrationId: string) =>
  request<{ message: string }>(`/api/evals/auto-grade/${integrationId}/stop`, {
    method: "POST",
  });

// --- Eval Sessions ---

export const triggerSession = (
  experimentIds: string[],
  datasetIds?: string[],
  concurrency?: number,
  maxTurns?: number,
  useBatch?: boolean,
) =>
  request<TriggerSessionResponse>("/api/evals/trigger/session", {
    method: "POST",
    body: JSON.stringify({
      experiment_ids: experimentIds,
      dataset_ids: datasetIds || null,
      concurrency,
      max_turns: maxTurns,
      use_batch: useBatch,
    }),
  });

export const getEvalSessions = () =>
  request<EvalSessionListResponse>("/api/evals/sessions");

export const getEvalSession = (id: string) =>
  request<EvalSession>(`/api/evals/sessions/${id}`);

export const stopEvalSession = (id: string) =>
  request<{ message: string; session_id: string }>(`/api/evals/sessions/${id}/stop`, { method: "POST" });

// --- Top Questions Analysis ---

export const analyzeTopQuestions = (body: {
  from_date?: string;
  to_date?: string;
  environment?: string;
  limit?: number;
  selected_feedback_ids?: string[];
}) =>
  request<{ analysis_id: string; status: string }>("/api/feedback/top-questions", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getTopQuestionsAnalysis = (analysisId: string) =>
  request<import("../api-types/data").TopQuestionsResponse>(`/api/feedback/top-questions/${analysisId}`);

export const getLatestTopQuestions = () =>
  request<import("../api-types/data").TopQuestionsResponse>("/api/feedback/top-questions/latest");

export const stopTopQuestionsAnalysis = (analysisId: string) =>
  request<{ message: string; status: string }>(
    `/api/feedback/top-questions/${analysisId}/stop`,
    { method: "POST" }
  );

// --- Feedback Theme Clustering ---

export const analyzeFeedbackThemes = (body: {
  from_date?: string;
  to_date?: string;
  environment?: string;
  limit?: number;
  selected_feedback_ids?: string[];
}) =>
  request<{ analysis_id: string; status: string }>("/api/feedback/themes", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getFeedbackThemesAnalysis = (analysisId: string) =>
  request<import("../api-types/data").FeedbackThemesResponse>(`/api/feedback/themes/${analysisId}`);

export const getLatestFeedbackThemes = () =>
  request<import("../api-types/data").FeedbackThemesResponse>("/api/feedback/themes/latest");

export const stopFeedbackThemesAnalysis = (analysisId: string) =>
  request<{ message: string; status: string }>(
    `/api/feedback/themes/${analysisId}/stop`,
    { method: "POST" }
  );

// --- Suggestions ---

export const generateSuggestions = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<import("../api-types/data").SuggestionRunResponse>(
    `/api/feedback/generate-suggestions${qs}`,
    { method: "POST" }
  );
};

export const getSuggestionRun = (runId: string) =>
  request<import("../api-types/data").SuggestionRunResponse>(
    `/api/feedback/generate-suggestions/${runId}`
  );

export const getLatestSuggestions = () =>
  request<import("../api-types/data").SuggestionRunResponse>(
    "/api/feedback/generate-suggestions/latest"
  );

export const stopSuggestionRun = (runId: string) =>
  request<import("../api-types/data").SuggestionRunResponse>(
    `/api/feedback/generate-suggestions/${runId}/stop`,
    { method: "POST" }
  );

export const acceptSuggestion = (datasetId: string, body: TestCaseCreateBody) =>
  request<TestCaseItem>(`/api/datasets/${datasetId}/cases/from-suggestion`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const regenerateSuggestionExpectedAnswer = (feedbackId: string) =>
  request<{ expected_answer: string | null }>(
    `/api/feedback/suggestions/${feedbackId}/regenerate-expected-answer`,
    { method: "POST" },
  );

// --- Traces Import ---

export const importTraces = (body: { traces: unknown[]; filename?: string }) =>
  request<{ imported: number; message: string }>("/api/traces/import", {
    method: "POST",
    body: JSON.stringify(body),
  });

// --- Feedback Import ---

export const importFeedback = (body: { scores: unknown[]; filename?: string }) =>
  request<{ imported: number; message: string }>("/api/feedback/import", {
    method: "POST",
    body: JSON.stringify(body),
  });

// --- Import History ---

export const getImportHistory = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<JsonImportListResponse>(`/api/imports${qs}`);
};
