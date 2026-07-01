/**
 * API functions for Evaluators.
 */

import type {
  EvaluatorItem,
  EvaluatorListResponse,
  EvaluatorCreateBody,
  EvaluatorUpdateBody,
  GenerateExpressionResponse,
} from "../api-types";
import { request } from "./client";

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

export const bulkDeleteEvaluators = (ids: string[]) =>
  Promise.all(ids.map((id) => deleteEvaluator(id)));

// Generate a Code-evaluator DSL expression from a plain-language description via the LLM.
export const generateEvaluatorExpression = (description: string) =>
  request<GenerateExpressionResponse>("/api/evaluators/generate-expression", {
    method: "POST",
    body: JSON.stringify({ description }),
  });
