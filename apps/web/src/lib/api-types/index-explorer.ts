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

export interface IndexTreeDocument {
  id: string;
  title: string | null;
  url: string | null;
  snippet: string | null;
}

export interface IndexTreeResponse {
  level: "group" | "documents";
  key: string | null;
  groups: IndexTreeGroupNode[];
  documents: IndexTreeDocument[];
  parent_doc_count: number | null;
}

// --- Grouping advisor: LLM-suggested hierarchy + metadata-quality hints ---

export interface GroupingLevel {
  key: string;
  label: string;
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
  suggested_group_by: string[];
  summary: string;
  levels: GroupingLevel[];
  hints: MetadataHint[];
}

export interface IndexGroupingSuggestionResponse {
  suggestion: IndexGroupingSuggestion | null;
  suggested_at: string | null;
  model: string | null;
}
