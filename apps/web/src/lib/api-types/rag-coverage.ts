/**
 * Types for the RAG eval-coverage feature.
 * Mirror the backend contract in apps/api/app/schemas/index_providers.py.
 */

export interface IndexProvider {
  id: string;
  type: string; // "azure_search" (others reserved)
  name: string;
  base_url?: string | null; // endpoint URL
  config: Record<string, unknown>; // e.g. { index_name: "prod-index" }
  created_at: string;
  updated_at: string;
}

export interface IndexProviderCreateBody {
  type: string;
  name: string;
  api_key: string;
  base_url?: string;
  config?: Record<string, unknown>;
}

export interface IndexProviderUpdateBody {
  name?: string;
  api_key?: string;
  base_url?: string;
  config?: Record<string, unknown>;
}

export interface TestConnectionResult {
  ok: boolean;
  document_count?: number | null;
  error?: string | null;
}

export interface PartitionKey {
  key: string;
  label: string;
  multivalued: boolean;
  metadata: Record<string, unknown>;
}

export interface CoverageRow {
  value: string;
  indexed_count: number;
  covering_cases: number;
  covered: boolean;
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

export interface CoverageRun {
  id: string;
  provider_id: string;
  status: CoverageRunStatus;
  error?: string | null;
  partition_key: string;
  dataset_ids?: string[] | null;
  suggest: boolean;
  min_covering_cases: number;
  total: number;
  processed: number;
  results?: CoverageResults | null;
  suggestions: CoverageSuggestion[];
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
}

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

export interface AnalyzeResponse {
  run_id: string;
  status: string;
}
