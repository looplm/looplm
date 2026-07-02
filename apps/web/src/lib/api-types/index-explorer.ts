/**
 * Types for the read-only index explorer (Data Sources page).
 * Mirror the backend contract in apps/api/app/schemas/index_explorer.py.
 *
 * Hand-written (not generated) — this surface has no client-coupled schema.gen
 * dependency, so keep these in sync with the Pydantic models manually.
 */

export interface IndexProviderOption {
  id: string;
  type: string;
  name: string;
}

export interface IndexPartitionKey {
  key: string;
  label: string;
  multivalued: boolean;
  metadata: Record<string, unknown>;
}

export interface IndexSummary {
  document_count: number;
  partition_keys: IndexPartitionKey[];
}

export interface IndexTreeGroupNode {
  value: string;
  doc_count: number;
  has_children: boolean;
}

export interface IndexTreeSection {
  key: string;
  label: string;
  groups: IndexTreeGroupNode[];
}

export interface IndexTreeDocument {
  id: string;
  title: string | null;
  url: string | null;
  snippet: string | null;
}

export interface IndexTreeResponse {
  level: "group" | "documents";
  sections: IndexTreeSection[];
  documents: IndexTreeDocument[];
}

// --- Files tab: file-type overview + filename search → chunks-of-a-file ---

export interface IndexFileTypeValue {
  value: string;
  count: number;
}

export interface IndexFileTypesResponse {
  field: string | null;
  values: IndexFileTypeValue[];
}

export interface IndexFileMatch {
  key: string;
  value: string;
  label: string;
  kind: "attachment" | "page";
  chunk_count: number;
  url: string | null;
}

export interface IndexFileListResponse {
  data: IndexFileMatch[];
}

export interface IndexFileChunk {
  id: string;
  index: number;
  ordinal: string | null;
  title: string | null;
  url: string | null;
  snippet: string | null;
}

export interface IndexFileChunksResponse {
  label: string;
  ordinal_available: boolean;
  documents: IndexFileChunk[];
}

// --- Grouping advisor: LLM-suggested hierarchy + metadata-quality hints ---

export interface GroupingLevel {
  keys: string[];
  reason: string;
}

export interface MetadataHint {
  severity: "info" | "warning";
  title: string;
  message: string;
  field: string | null;
  suggested_field: string | null;
}

export interface IndexGroupingSuggestion {
  // Ordered top to bottom; each inner array is the field(s) at that level
  // (more than one = parallel facets shown side by side).
  suggested_levels: string[][];
  summary: string;
  levels: GroupingLevel[];
  hints: MetadataHint[];
}

export interface IndexGroupingSuggestionResponse {
  suggestion: IndexGroupingSuggestion | null;
  suggested_at: string | null;
  model: string | null;
}
