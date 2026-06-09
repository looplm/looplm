/**
 * Type definitions for Evaluations, Eval Trigger, and Evaluators.
 *
 * Generated from the backend OpenAPI schema — do not hand-edit shapes here.
 * Regenerate with `pnpm gen:api` after changing the Pydantic schemas.
 * The CLIENT-SIDE section at the bottom has no backend schema and is hand-maintained.
 */

import type { components } from "./schema.gen";

type S = components["schemas"];

// --- Evaluations ---
export type GraderSummaryItem = S["GraderSummaryItem"];
export type ScoreSummaryItem = S["ScoreSummaryItem"];
export type EvalRunListItem = S["EvalRunListItem"];
export type EvalRunListResponse = S["EvalRunListResponse"];
export type GraderResultSummary = S["GraderResultSummary"];
export type EvalResultSummary = S["EvalResultSummary"];
export type ClassifyFailuresResponse = S["ClassifyFailuresResponse"];
export type EvalResultItem = S["EvalResultItem"];
export type EvalRunDetail = S["EvalRunDetail"];
export type EvalRunStats = S["EvalRunStats"];

// --- Eval Trigger ---
export type DatasetPickerItem = S["DatasetPickerItem"];
export type DatasetPickerResponse = S["DatasetPickerResponse"];
export type EvalJob = S["EvalJobResponse"];
export type EvalJobListResponse = S["EvalJobListResponse"];
export type TriggerEvalResponse = S["TriggerEvalResponse"];

// --- Evaluators ---
export type EvaluatorItem = S["EvaluatorResponse"];
export type EvaluatorListResponse = S["EvaluatorListResponse"];
export type EvaluatorCreateBody = S["EvaluatorCreate"];
export type EvaluatorUpdateBody = S["EvaluatorUpdate"];

// --- Eval Report ---
export type ReportTraceInfo = S["ReportTraceInfo"];
export type ReportGraderEntry = S["ReportGraderEntry"];
export type ReportTestCaseDetail = S["ReportTestCaseDetail"];
export type ReportGraderFailure = S["ReportGraderFailure"];
export type ReportFailureAnalysis = S["ReportFailureAnalysis"];
export type ReportSummary = S["ReportSummary"];
export type ReportEvalRunInfo = S["ReportEvalRunInfo"];
export type EvalReportResponse = S["EvalReportResponse"];

// --- Multi-Run Report ---
export type MultiRunReportResponse = S["MultiRunReportResponse"];

// --- Saved Reports ---
export type EvalReportListItem = S["EvalReportListItem"];
export type EvalReportListResponse = S["EvalReportListResponse"];
export type EvalReportDetail = S["EvalReportDetail"];

// --- Experiments ---
export type Experiment = S["ExperimentResponse"];
export type ExperimentListResponse = S["ExperimentListResponse"];
export type ExperimentCreateBody = S["ExperimentCreate"];
export type ExperimentUpdateBody = S["ExperimentUpdate"];

// --- Eval Sessions ---
export type EvalSession = S["EvalSessionResponse"];
export type EvalSessionListResponse = S["EvalSessionListResponse"];
export type TriggerSessionResponse = S["TriggerSessionResponse"];

// --- Code Agent (Eval-driven code suggestions) ---
export type CodeSuggestionItem = S["CodeSuggestionItem"];
export type OpenCodeAnalysisResponse = S["OpenCodeAnalysisResponse"];

// --- Client-side only (inlined on parents, no named backend schema) ---

export interface EvalGraderResult {
  pass: boolean;
  reason?: string;
  skipped?: boolean;
  details?: Record<string, unknown>;
}

export interface ConversationTurn {
  turn: number;
  prompt: string;
  response: string | null;
  pass: boolean;
  error?: string;
  graders: Record<string, { pass: boolean; reason?: string; skipped?: boolean }>;
}

/** Stored on EvalResultItem.metadata.root_cause — the full attribution detail. */
export interface RootCauseDetail {
  category: "retrieval" | "generation" | "task_spec" | "indeterminate";
  confidence: "high" | "low";
  source: "deterministic" | "llm";
  evidence: string;
  missing_facts?: string[];
}

export interface EvalJobConfig {
  filter_mode?: "as_configured" | "no_filters" | "both";
  concurrency?: number;
  max_turns?: number;
  use_batch?: boolean;
}

export interface EvalJobLogsResponse {
  log: string;
  total_lines: number;
}

export interface ReportPreconditions {
  filter_mode?: string;
  team_filter?: string[];
  tag_filter?: string[];
  context_filters?: Record<string, unknown>;
}
