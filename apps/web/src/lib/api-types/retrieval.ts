/**
 * Retrieval section types — the aggregate retrieval pipeline flow chart.
 *
 * Hand-written (not derived from schema.gen.ts) so the Retrieval page does not depend on
 * an OpenAPI regeneration. Mirrors app/schemas/retrieval.py.
 */

export interface RetrievalMetric {
  label: string;
  value: string;
  hint?: string | null;
  tone?: "good" | "warn" | "bad" | "muted" | null;
}

export interface RetrievalPipelineNode {
  id: string;
  label: string;
  sublabel?: string | null;
  group?: string | null;
  provider?: string | null;
  status: "active" | "no_data";
  description?: string | null;
  metrics: RetrievalMetric[];
}

export interface RetrievalPipelineEdge {
  source: string;
  target: string;
  label?: string | null;
  kind: "main" | "fallback";
}

export interface RetrievalPipelineResponse {
  available: boolean;
  traces_analyzed: number;
  rag_traces: number;
  nodes: RetrievalPipelineNode[];
  edges: RetrievalPipelineEdge[];
  span_names: Record<string, string>;
}

export interface RetrievalTargets {
  recall: number;
  ndcg: number;
  mrr: number;
  hit_rate: number;
  precision: number;
}

// --- Chunk-level human relevance labeling ---

export interface ChunkForLabeling {
  chunk_id?: string | null;
  title?: string | null;
  url?: string | null;
  content?: string | null;
  content_preview?: string | null;
  heading_context?: string | null;
  pdf_page_number?: number | null;
  score?: number | null;
  rank: number;
  relevant?: boolean | null;
  labeled_by?: string | null;
}

export interface LabelingCase {
  test_id: string;
  input?: string | null;
  chunks: ChunkForLabeling[];
  labeled_count: number;
  relevant_count: number;
  complete: boolean;
  slice?: string | null;
  labelers: string[];
}

export type RiskSlice = "broad" | "safety" | "adversarial";

export interface LabelingRunResponse {
  available: boolean;
  run_id?: string | null;
  run_name?: string | null;
  total_cases: number;
  labelable_cases: number;
  cases: LabelingCase[];
}

export interface ChunkMetadataResponse {
  provider_connected: boolean;
  available: boolean;
  fields?: Record<string, unknown> | null;
}

export interface ChunkLabelUpsert {
  test_id: string;
  chunk_id: string;
  relevant: boolean;
  content_preview?: string | null;
  url?: string | null;
  title?: string | null;
}

// --- Multi-head candidate pool (trace captures ∪ index search heads) ---

export interface PooledChunkForLabeling {
  chunk_id: string;
  title?: string | null;
  url?: string | null;
  content_preview?: string | null;
  score?: number | null;
  // Heads that surfaced this chunk: "trace" | "keyword" | "vector" | "hybrid".
  provenance: string[];
  relevant?: boolean | null;
  labeled_by?: string | null;
}

export interface LabelingPoolResponse {
  test_id: string;
  input?: string | null;
  provider_connected: boolean;
  pool_size: number;
  heads_ran: string[];
  heads_failed: Record<string, string>;
  chunks: PooledChunkForLabeling[];
}

// --- Quantitative retrieval-quality metrics (eval-run based) ---

export interface RetrievalCaseMetrics {
  test_id: string;
  input?: string | null;
  expected_count: number;
  retrieved_count: number;
  recall_at_k: Record<string, number>;
  ndcg_at_k: Record<string, number>;
  mrr?: number | null;
  first_relevant_rank?: number | null;
  hit: boolean;
  missing_urls: string[];
  // Incomplete-judgment-safe (chunk-label path only); null/empty on the URL path.
  bpref?: number | null;
  condensed_ndcg_at_k?: Record<string, number>;
  slice?: string | null;
}

export interface SliceMetrics {
  slice: string;
  case_count: number;
  recall_at_k: Record<string, number>;
  ndcg_at_k: Record<string, number>;
  bpref?: number | null;
}

export interface RetrievalRunMetrics {
  available: boolean;
  run_id?: string | null;
  run_name?: string | null;
  total_cases: number;
  evaluated_cases: number;
  ks: number[];
  recall_at_k: Record<string, number>;
  precision_at_k: Record<string, number>;
  hit_rate_at_k: Record<string, number>;
  ndcg_at_k: Record<string, number>;
  mrr?: number | null;
  // Incomplete-judgment-safe roll-ups (chunk-label path only); see RetrievalCaseMetrics.
  bpref?: number | null;
  condensed_ndcg_at_k?: Record<string, number>;
  slices?: SliceMetrics[];
  cases: RetrievalCaseMetrics[];
}
