/**
 * API functions for Feedback.
 */

import type {
  FeedbackListResponse,
  FeedbackStatsResponse,
  FeedbackScoreDetail,
  FeedbackEvaluateResponse,
} from "../api-types";
import { request } from "./client";

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
