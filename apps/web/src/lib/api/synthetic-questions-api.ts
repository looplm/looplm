/**
 * API functions for synthetic question generation (Data Sources page).
 */

import type {
  SyntheticQuestionRunDetail,
  SyntheticQuestionRunRequest,
  SyntheticQuestionRunSummary,
} from "../api-types/synthetic-questions";
import { request } from "./client";

export const startSyntheticQuestionRun = (body: SyntheticQuestionRunRequest) =>
  request<{ run_id: string; status: string }>("/api/synthetic-questions/runs", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const listSyntheticQuestionRuns = (providerId: string) =>
  request<{ data: SyntheticQuestionRunSummary[] }>(
    `/api/synthetic-questions/runs?provider_id=${encodeURIComponent(providerId)}`,
  );

export const getSyntheticQuestionRun = (runId: string) =>
  request<SyntheticQuestionRunDetail>(`/api/synthetic-questions/runs/${runId}`);

export const cancelSyntheticQuestionRun = (runId: string) =>
  request<{ run_id: string; status: string }>(
    `/api/synthetic-questions/runs/${runId}/cancel`,
    { method: "POST" },
  );

export const deleteSyntheticQuestionRun = (runId: string) =>
  request<void>(`/api/synthetic-questions/runs/${runId}`, { method: "DELETE" });
