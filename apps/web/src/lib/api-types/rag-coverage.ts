/**
 * Types for the RAG eval-coverage feature.
 * Mirror the backend contract in apps/api/app/schemas/index_providers.py.
 *
 * Generated from the backend OpenAPI schema — do not hand-edit shapes here.
 * Regenerate with `pnpm gen:api` after changing the Pydantic schemas.
 * The CLIENT-SIDE section at the bottom is inlined on parents (no named schema).
 */

import type { components } from "./schema.gen";

type S = components["schemas"];

export type IndexProvider = S["IndexProviderResponse"];
export type IndexProviderCreateBody = S["IndexProviderCreate"];
export type IndexProviderUpdateBody = S["IndexProviderUpdate"];
export type TestConnectionResult = S["TestConnectionResponse"];
export type PartitionKey = S["PartitionKeyResponse"];
export type PartitionAcknowledgement = S["AcknowledgementResponse"];
export type AcknowledgementCreateBody = S["AcknowledgementCreate"];
export type CoverageRun = S["CoverageRunResponse"];
export type CoverageRunSummary = S["CoverageRunSummary"];
export type CoverageCategoryOverview = S["CoverageCategoryOverview"];
export type AnalyzeResponse = S["app__schemas__index_providers__AnalyzeResponse"];

// --- Client-side only (inlined on parents, no named backend schema) ---

export interface CoverageRow {
  value: string;
  indexed_count: number;
  covering_cases: number;
  covered: boolean;
}

export type PartitionIssueKind = "near_duplicate" | "tiny_bucket" | "empty_or_placeholder";
export type PartitionIssueSeverity = "high" | "medium" | "low";

export interface PartitionIssue {
  kind: PartitionIssueKind;
  value: string;
  severity: PartitionIssueSeverity;
  message: string;
  related_values: string[];
}

export interface CoverageResults {
  partition_key: string;
  total_values: number;
  covered_values: number;
  total_docs: number;
  covered_docs: number;
  value_coverage_pct: number;
  doc_coverage_pct: number;
  rows: CoverageRow[];
  issues?: PartitionIssue[];
}

export interface CoverageSuggestion {
  partition_value: string;
  prompt: string;
  acceptance_criteria: string;
  tag_filter: string[];
  team_filter: string[];
  expected_source_types: string[];
  context_filters: Record<string, string>;
}

export type CoverageRunStatus = "pending" | "running" | "completed" | "failed";

export interface StartAnalysisBody {
  provider_id: string;
  partition_key: string;
  dataset_ids?: string[];
  suggest: boolean;
  min_covering_cases?: number;
  sample_n?: number;
  max_questions_per_gap?: number;
  max_gaps_to_suggest?: number;
}
