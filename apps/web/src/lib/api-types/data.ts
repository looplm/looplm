/**
 * Type definitions for Prompts, Feedback, and Test Datasets.
 *
 * Generated from the backend OpenAPI schema — do not hand-edit shapes here.
 * Regenerate with `pnpm gen:api` after changing the Pydantic schemas.
 * The CLIENT-SIDE section at the bottom has no backend schema and is hand-maintained.
 */

import type { components } from "./schema.gen";

type S = components["schemas"];

// --- Prompts ---
export type PromptItem = S["PromptOut"];
export type PromptListResponse = S["PromptListResponse"];
export type AntiPattern = S["AntiPattern"];
export type PromptReviewResult = S["PromptReviewResult"];
export type PromptReviewListResponse = S["PromptReviewListResponse"];

// --- Feedback ---
export type FeedbackScoreItem = S["FeedbackScoreItem"];
export type FeedbackListResponse = S["FeedbackListResponse"];
export type FeedbackTrend = S["FeedbackTrend"];
export type GraderStats = S["GraderStats"];
export type GraderTrend = S["GraderTrend"];
export type FeedbackStatsResponse = S["FeedbackStatsResponse"];
export type FeedbackScoreDetail = S["FeedbackScoreDetail"];

// --- Feedback Evaluation ---
export type FeedbackEvalItem = S["FeedbackEvalItem"];
export type FeedbackEvalSummary = S["FeedbackEvalSummary"];
export type FeedbackEvaluateResponse = S["FeedbackEvaluateResponse"];
export type FeedbackEvaluatorConfig = S["FeedbackEvaluatorConfigResponse"];

// --- Top Questions Analysis ---
export type TopQuestionItem = S["TopQuestionItem"];
export type TopQuestionTheme = S["TopQuestionTheme"];
export type TopQuestionsResponse = S["TopQuestionsResponse"];
export type SuggestionRunResponse = S["SuggestionRunResponse"];

// --- Feedback Theme Clustering ---
export type FeedbackThemeItem = S["FeedbackThemeItem"];
export type FeedbackTheme = S["FeedbackTheme"];
export type FeedbackThemesResponse = S["FeedbackThemesResponse"];

// --- Test Datasets ---
export type TestDatasetItem = S["TestDatasetItem"];
export type TestDatasetListResponse = S["TestDatasetListResponse"];
export type TestCaseItem = S["TestCaseItem"];
export type TestDatasetDetail = S["TestDatasetDetail"];
export type TestCaseSuggestion = S["TestCaseSuggestion"];
export type TestCaseCreateBody = S["TestCaseCreate"];
export type TestCaseUpdateBody = S["TestCaseUpdate"];

// --- Import History ---
export type JsonImportItem = S["JsonImportItem"];
export type JsonImportListResponse = S["JsonImportListResponse"];

// --- Client-side only (no backend schema) ---

/** Frontend export/serialization shape (camelCase) — not part of the API contract. */
export interface TestDatasetExport {
  name: string;
  description: string | null;
  testCases: {
    id: string;
    prompt: string;
    expectedAnswer: string | null;
    expectedSources: string[];
    teamFilter: string[];
    tagFilter: string[];
    filters: Record<string, string>;
    folder: string | null;
    document: string | null;
    expectedPageUrls: string[];
    expectedSourceTypes: string[];
    maxAnswerLength: number | null;
    metadata?: Record<string, unknown>;
  }[];
}
