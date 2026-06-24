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
  content_preview?: string | null;
  score?: number | null;
  rank: number;
  relevant?: boolean | null;
}

export interface LabelingCase {
  test_id: string;
  input?: string | null;
  chunks: ChunkForLabeling[];
  labeled_count: number;
  relevant_count: number;
}

export interface LabelingRunResponse {
  available: boolean;
  run_id?: string | null;
  run_name?: string | null;
  total_cases: number;
  labelable_cases: number;
  cases: LabelingCase[];
}

export interface ChunkLabelUpsert {
  test_id: string;
  chunk_id: string;
  relevant: boolean;
  content_preview?: string | null;
  url?: string | null;
  title?: string | null;
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
  cases: RetrievalCaseMetrics[];
}
