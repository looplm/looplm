/**
 * Types for the wanted-status source registry (Data Sources page).
 * Hand-written mirror of apps/api/app/schemas/source_registry.py.
 */

export interface SourceExpectation {
  id: string;
  provider_id: string;
  name: string;
  html_url: string | null;
  pdf_url: string | null;
  adapter_tag: string | null;
  typ: string | null;
  sparte: string | null;
  thema: string | null;
  publisher: string | null;
  hierarchie: string | null;
  update_frequency: string | null;
  comment: string | null;
  ack_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface CsvImportResult {
  created: number;
  updated: number;
  deleted: number;
  skipped_rows: number;
  total: number;
  warnings: string[];
}

export type GapRowStatus =
  | "covered_url"
  | "covered_title"
  | "review"
  | "missing"
  | "acked";

export interface GapRowResult {
  expectation_id: string;
  name: string;
  adapter_tag: string | null;
  status: GapRowStatus;
  detail: string;
  chunk_count: number;
  matched_title: string | null;
  matched_url: string | null;
  title_score: number | null;
}

export interface GapRunSummary {
  id: string;
  provider_id: string;
  status: string;
  total: number;
  processed: number;
  covered: number;
  missing: number;
  review: number;
  acked: number;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface SourceChunk {
  id: string;
  index: number;
  ordinal: string | null;
  title: string | null;
  url: string | null;
  text: string | null;
}

export interface SourceChunksResponse {
  expectation_id: string;
  name: string;
  resolution: "url" | "title" | "none";
  resolved: boolean;
  kind: string | null;
  matched_title: string | null;
  matched_url: string | null;
  chunk_count: number;
  ordinal_available: boolean;
  missing_ordinals: number[];
  duplicate_ordinals: number[];
  gaps_truncated: boolean;
  chunks: SourceChunk[];
}

export interface SourceScanRun {
  id: string;
  provider_id: string;
  scope: "all" | "dlq";
  status: string; // pending | running | completed | failed | cancelled
  total: number;
  processed: number;
  failed: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface SourceScanResultItem {
  expectation_id: string;
  resolution: "url" | "title" | "none";
  resolved: boolean;
  kind: string | null;
  matched_url: string | null;
  matched_title: string | null;
  chunk_count: number;
  missing_chunk_count: number;
  ordinal_checked: boolean;
  execution_status: "ok" | "error";
  error: string | null;
  scanned_at: string;
}

export interface SourceScanSummary {
  total?: number;
  not_indexed?: number;
  incomplete?: number;
  errored?: number;
  ok?: number;
}

export interface SourceScanResultsResponse {
  data: SourceScanResultItem[];
  summary: SourceScanSummary;
  latest_run: SourceScanRun | null;
}

export interface GapRunDetail {
  id: string;
  provider_id: string;
  status: string;
  total: number;
  processed: number;
  error: string | null;
  results: {
    summary: {
      total: number;
      by_status: Record<string, number>;
      covered: number;
      missing: number;
      review: number;
      acked: number;
    };
    rows: GapRowResult[];
  } | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}
