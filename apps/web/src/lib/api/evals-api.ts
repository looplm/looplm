/**
 * API functions for Prompts, Feedback, Evaluations, Eval Trigger,
 * Evaluators, and Datasets.
 */

import type {
  PromptItem,
  PromptListResponse,
  PromptReviewResult,
  PromptReviewListResponse,
  FeedbackListResponse,
  FeedbackStatsResponse,
  FeedbackScoreDetail,
  FeedbackEvaluateResponse,
  EvalRunListResponse,
  EvalRunDetail,
  EvalRunListItem,
  EvalRunStats,
  DatasetPickerResponse,
  EvalJob,
  EvalJobListResponse,
  EvalJobLogsResponse,
  TriggerEvalResponse,
  EvaluatorItem,
  EvaluatorListResponse,
  EvaluatorCreateBody,
  EvaluatorUpdateBody,
  TestDatasetItem,
  TestDatasetListResponse,
  TestCaseItem,
  TestDatasetDetail,
  TestCaseSuggestion,
  TestCaseCreateBody,
  TestDatasetExport,
  JsonImportListResponse,
  EvalReportResponse,
  CodeSuggestionItem,
  OpenCodeAnalysisResponse,
  Experiment,
  ExperimentListResponse,
  ExperimentCreateBody,
  ExperimentUpdateBody,
  EvalSession,
  EvalSessionListResponse,
  TriggerSessionResponse,
} from "../api-types";
import { request } from "./client";

// --- Prompts ---

export const getPrompts = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<PromptListResponse>(`/api/prompts${qs}`);
};

export const syncPrompts = (integrationId: string) =>
  request<{ synced: number; message: string }>(`/api/prompts/sync/${integrationId}`, { method: "POST" });

export const importPrompts = (prompts: { name: string; template: string; version?: number; variables?: string[]; metadata?: Record<string, unknown> }[], filename?: string) =>
  request<{ synced: number; message: string }>("/api/prompts/import", {
    method: "POST",
    body: JSON.stringify({ prompts, filename }),
  });

export const getPromptById = (id: string) =>
  request<PromptItem>(`/api/prompts/${id}`);

export const reviewPrompt = (id: string) =>
  request<PromptReviewResult>(`/api/prompts/${id}/review`, { method: "POST" });

export const getPromptReviews = (id: string) =>
  request<PromptReviewListResponse>(`/api/prompts/${id}/reviews`);

export const getPromptVersions = (id: string) =>
  request<PromptListResponse>(`/api/prompts/${id}/versions`);

// --- Feedback ---

export const getFeedback = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<FeedbackListResponse>(`/api/feedback${qs}`);
};

export const getFeedbackStats = (
  params: Record<string, string> | number = 30
) => {
  if (typeof params === "number") {
    return request<FeedbackStatsResponse>(`/api/feedback/stats?days=${params}`);
  }
  const qs = new URLSearchParams(params).toString();
  return request<FeedbackStatsResponse>(`/api/feedback/stats?${qs}`);
};

export const getFeedbackById = (id: string) =>
  request<FeedbackScoreDetail>(`/api/feedback/${id}`);

export const evaluateFeedback = (body: {
  from_date?: string;
  to_date?: string;
  environment?: string;
  limit?: number;
}) =>
  request<{ evaluation_id: string; status: string }>("/api/feedback/evaluate", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getFeedbackEvaluation = (evaluationId: string) =>
  request<FeedbackEvaluateResponse>(`/api/feedback/evaluate/${evaluationId}`);

export const stopFeedbackEvaluation = (evaluationId: string) =>
  request<{ message: string; status: string }>(`/api/feedback/evaluate/${evaluationId}/stop`, { method: "POST" });

export const evaluateSingleFeedback = (feedbackId: string) =>
  request<{ verdict: string; reasoning: string; confidence: number }>(`/api/feedback/evaluate-single/${feedbackId}`, { method: "POST" });

export const getFeedbackEvaluatorConfig = () =>
  request<import("../api-types/data").FeedbackEvaluatorConfig>("/api/feedback/evaluator/config");

export const updateFeedbackEvaluatorConfig = (body: {
  prompt?: string;
  verdicts?: string[];
  default_verdict?: string;
  model?: string | null;
}) =>
  request<import("../api-types/data").FeedbackEvaluatorConfig>("/api/feedback/evaluator/config", {
    method: "PUT",
    body: JSON.stringify(body),
  });

// --- Evaluations ---

export const getEvalRuns = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<EvalRunListResponse>(`/api/evals${qs}`);
};

export const getEvalRun = (id: string) =>
  request<EvalRunDetail>(`/api/evals/${id}`);

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

export const bulkDeleteEvaluators = (ids: string[]) =>
  Promise.all(ids.map((id) => deleteEvaluator(id)));

// --- Eval Trigger ---

export const getDatasetsPicker = () =>
  request<DatasetPickerResponse>("/api/evals/trigger/datasets");

export const triggerEval = (datasetIds?: string[], concurrency?: number, filterMode?: string, useBatch?: boolean) =>
  request<TriggerEvalResponse>("/api/evals/trigger", {
    method: "POST",
    body: JSON.stringify({ dataset_ids: datasetIds || null, concurrency, filter_mode: filterMode, use_batch: useBatch }),
  });

export const rerunEval = (runId: string) =>
  request<TriggerEvalResponse>(`/api/evals/${runId}/rerun`, {
    method: "POST",
  });

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

// --- Experiments ---

export const getExperiments = () =>
  request<ExperimentListResponse>("/api/experiments");

export const getExperiment = (id: string) =>
  request<Experiment>(`/api/experiments/${id}`);

export const createExperiment = (body: ExperimentCreateBody) =>
  request<Experiment>("/api/experiments", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateExperiment = (id: string, body: ExperimentUpdateBody) =>
  request<Experiment>(`/api/experiments/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteExperiment = (id: string) =>
  request<void>(`/api/experiments/${id}`, { method: "DELETE" });

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

// --- Evaluators ---

export const getEvaluators = () =>
  request<EvaluatorListResponse>("/api/evaluators");

export const getEvaluator = (id: string) =>
  request<EvaluatorItem>(`/api/evaluators/${id}`);

export const createEvaluator = (body: EvaluatorCreateBody) =>
  request<EvaluatorItem>("/api/evaluators", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateEvaluator = (id: string, body: EvaluatorUpdateBody) =>
  request<EvaluatorItem>(`/api/evaluators/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteEvaluator = (id: string) =>
  request<void>(`/api/evaluators/${id}`, { method: "DELETE" });

export const importEvaluators = (evaluators: EvaluatorCreateBody[]) =>
  request<{ created: number; skipped: number; total: number; data: EvaluatorItem[] }>("/api/evaluators/import", {
    method: "POST",
    body: JSON.stringify({ evaluators }),
  });

export const syncEvaluators = () =>
  request<EvaluatorListResponse>("/api/evaluators/sync", { method: "POST" });

// --- Datasets ---

export const getDatasets = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<TestDatasetListResponse>(`/api/datasets${qs}`);
};

export const createDataset = (body: { name: string; description?: string; tags?: string[] }) =>
  request<TestDatasetItem>("/api/datasets", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getDataset = (id: string) =>
  request<TestDatasetDetail>(`/api/datasets/${id}`);

export const updateDataset = (id: string, body: { name?: string; description?: string; tags?: string[] }) =>
  request<TestDatasetItem>(`/api/datasets/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteDataset = (id: string) =>
  request<void>(`/api/datasets/${id}`, { method: "DELETE" });

export const bulkDeleteDatasets = (ids: string[]) =>
  Promise.all(ids.map((id) => deleteDataset(id)));

export const createTestCase = (datasetId: string, body: TestCaseCreateBody) =>
  request<TestCaseItem>(`/api/datasets/${datasetId}/cases`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateTestCase = (datasetId: string, caseId: string, body: Partial<TestCaseCreateBody>) =>
  request<TestCaseItem>(`/api/datasets/${datasetId}/cases/${caseId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteTestCase = (datasetId: string, caseId: string) =>
  request<void>(`/api/datasets/${datasetId}/cases/${caseId}`, { method: "DELETE" });

export const exportDataset = (id: string) =>
  request<TestDatasetExport>(`/api/datasets/${id}/export`);

export const importDataset = (body: { name?: string; description?: string; testCases: unknown[]; filename?: string }) =>
  request<TestDatasetItem>("/api/datasets/import", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getTestCaseSuggestions = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<TestCaseSuggestion[]>(`/api/datasets/suggestions${qs}`);
};

// --- Top Questions Analysis ---

export const analyzeTopQuestions = (body: {
  from_date?: string;
  to_date?: string;
  environment?: string;
  limit?: number;
}) =>
  request<{ analysis_id: string; status: string }>("/api/feedback/top-questions", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getTopQuestionsAnalysis = (analysisId: string) =>
  request<import("../api-types/data").TopQuestionsResponse>(`/api/feedback/top-questions/${analysisId}`);

export const getLatestTopQuestions = () =>
  request<import("../api-types/data").TopQuestionsResponse>("/api/feedback/top-questions/latest");

// --- Suggestions ---

export const generateSuggestions = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<TestCaseSuggestion[]>(`/api/feedback/generate-suggestions${qs}`, {
    method: "POST",
  });
};

export const acceptSuggestion = (datasetId: string, body: TestCaseCreateBody) =>
  request<TestCaseItem>(`/api/datasets/${datasetId}/cases/from-suggestion`, {
    method: "POST",
    body: JSON.stringify(body),
  });

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

// --- Code Agent (Eval-driven code suggestions) ---

export const triggerCodeAgentAnalysis = (
  evalRunId: string,
  extraContext = "",
  filePatterns?: string[],
  mode: "quick" | "detailed" = "detailed",
) =>
  request<{ analysis_id: string; status: string }>(
    `/api/code-agent/${evalRunId}/analyze`,
    {
      method: "POST",
      body: JSON.stringify({
        extra_context: extraContext,
        file_patterns: filePatterns || null,
        analysis_mode: mode,
      }),
    },
  );

export const cancelCodeAgentAnalysis = (evalRunId: string) =>
  request<{ status: string; analysis_id: string }>(
    `/api/code-agent/${evalRunId}/cancel`,
    { method: "POST" },
  );

export const getCodeAgentAnalysis = (evalRunId: string) =>
  request<OpenCodeAnalysisResponse>(`/api/code-agent/${evalRunId}/analysis`);

export const updateCodeSuggestionStatus = (id: string, status: string) =>
  request<CodeSuggestionItem>(`/api/code-agent/suggestions/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
