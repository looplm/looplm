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
  // Graded relevance 0..3, or null when not yet judged.
  relevance?: number | null;
  labeled_by?: string | null;
  // The AI judge's graded relevance 0..3 for this chunk (read-only second opinion).
  ai_relevance?: number | null;
}

export interface LabelingCase {
  test_id: string;
  input?: string | null;
  // The chunks to judge come from the per-case index pool, not the case; kept for compat.
  chunks: ChunkForLabeling[];
  labeled_count: number;
  relevant_count: number;
  complete: boolean;
  slice?: string | null;
  labelers: string[];
}

export type RiskSlice = "broad" | "safety" | "adversarial";

export interface LabelingDatasetOption {
  id: string;
  name: string;
  test_count: number;
}

export interface LabelingRunResponse {
  available: boolean;
  dataset_id?: string | null;
  dataset_name?: string | null;
  datasets: LabelingDatasetOption[];
  total_cases: number;
  labelable_cases: number;
  cases: LabelingCase[];
}

export interface ChunkMetadataResponse {
  provider_connected: boolean;
  available: boolean;
  fields?: Record<string, unknown> | null;
}

// --- Inter-annotator agreement + adjudication ---

export interface AnnotatorAgreement {
  name: string;
  judged_count: number;
}

export interface PairwiseKappa {
  a: string;
  b: string;
  kappa: number;
  n: number;
}

export interface VoteEntry {
  labeler: string;
  // Graded relevance 0..3 this annotator assigned.
  relevance: number;
}

export interface Disagreement {
  test_id: string;
  chunk_id: string;
  title?: string | null;
  votes: VoteEntry[];
  // Adjudicated gold grade 0..3, or null if not yet resolved.
  gold?: number | null;
}

export interface AgreementReport {
  available: boolean;
  annotators: AnnotatorAgreement[];
  judged_items: number;
  overlap_count: number;
  double_judged_pct: number;
  pairwise: PairwiseKappa[];
  average_kappa?: number | null;
  disagreements: Disagreement[];
}

export interface ChunkLabelUpsert {
  test_id: string;
  chunk_id: string;
  // Graded relevance 0..3.
  relevance: number;
  content_preview?: string | null;
  url?: string | null;
  title?: string | null;
}

export interface AiJudgeResponse {
  test_id: string;
  // chunk_id -> AI-assigned graded relevance 0..3.
  grades: Record<string, number>;
  judged: number;
}

// One LLM call's user message: the full, untruncated chunk text for that batch.
export interface AiJudgePromptBatch {
  user_prompt: string;
  chunk_count: number;
}

// The exact prompt(s) the AI judge would send for a case (no LLM call), rendered server-side so
// the preview never drifts from what actually runs. Chunks go out in full; a large pool is split
// across several batches (calls), each with the query + full chunk text folded in.
export interface AiJudgePreviewResponse {
  test_id: string;
  system_prompt: string;
  batches: AiJudgePromptBatch[];
  chunk_count: number;
}

// --- Multi-head candidate pool (trace captures ∪ index search heads) ---

export interface PooledChunkForLabeling {
  chunk_id: string;
  title?: string | null;
  url?: string | null;
  content_preview?: string | null;
  score?: number | null;
  // Heads that surfaced this chunk: "trace" | "keyword" | "vector" | "hybrid" | "agentic".
  provenance: string[];
  // head -> 1-indexed rank the chunk held in that head's results, e.g. { vector: 3, hybrid: 2 }.
  // The pseudo-head "agentic" holds the best rank any planned sub-query gave the chunk.
  ranks: Record<string, number>;
  // Agentic sub-queries (from the LLM planner) that surfaced this chunk, when any did.
  agentic_queries?: string[];
  // Graded relevance 0..3, or null when not yet judged.
  relevance?: number | null;
  labeled_by?: string | null;
  // The AI judge's graded relevance 0..3 for this chunk (read-only second opinion).
  ai_relevance?: number | null;
}

// The queries a case's pool was built from: the base question + any agentic sub-queries.
export interface LabelingQueries {
  base: string[];
  agentic: string[];
}

export interface LabelingPoolResponse {
  test_id: string;
  input?: string | null;
  provider_connected: boolean;
  pool_size: number;
  heads_ran: string[];
  heads_failed: Record<string, string>;
  chunks: PooledChunkForLabeling[];
  // ISO timestamp of when this pool was last assembled against the index, or null.
  computed_at?: string | null;
  // The queries this pool was built from (base question + any agentic sub-queries).
  queries?: LabelingQueries | null;
}

// Result of planning agentic sub-queries for a case (persisted on the case).
export interface PlanQueriesResponse {
  test_id: string;
  base: string[];
  agentic: string[];
}

// Default rubrics the UI shows (and lets a reviewer edit before running).
export interface LabelingPromptDefaults {
  ai_judge: string;
  query_planner: string;
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
