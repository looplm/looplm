/**
 * API functions for the Code Agent (eval-driven code suggestions).
 */

import type {
  CodeSuggestionItem,
  OpenCodeAnalysisResponse,
} from "../api-types";
import { request } from "./client";

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
