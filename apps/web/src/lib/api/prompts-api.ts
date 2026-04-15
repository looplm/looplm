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
