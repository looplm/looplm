/**
 * API functions for Prompts.
 */

import type {
  PromptItem,
  PromptListResponse,
  PromptReviewResult,
  PromptReviewListResponse,
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

// --- Extract prompts from a connected GitHub codebase ---

export interface PromptExtractionStatus {
  id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  error: string | null;
  summary: string | null;
  files_analyzed: string[];
  extracted_count: number;
  total_cost_usd: number | null;
  num_turns: number | null;
  progress_message: string | null;
  progress_log: { t: string; msg: string }[];
  started_at: string | null;
  completed_at: string | null;
}

export const extractGithubPrompts = () =>
  request<{ extraction_id: string; status: string }>("/api/prompts/extract/github", {
    method: "POST",
  });

export const getGithubExtractionStatus = () =>
  request<PromptExtractionStatus>("/api/prompts/extract/github/latest");

export const cancelGithubExtraction = () =>
  request<{ status: string; extraction_id: string }>("/api/prompts/extract/github/cancel", {
    method: "POST",
  });
