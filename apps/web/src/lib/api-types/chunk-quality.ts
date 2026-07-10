/**
 * Types for chunk/metadata quality runs (Data Sources → Chunk quality tab).
 * Hand-written mirror of apps/api/app/schemas/chunk_quality.py and the engine's
 * ChunkQualityReport.to_dict() (app/index_providers/chunk_quality.py).
 */

export type Severity = "info" | "warn" | "critical";
export type QualityFamily =
  | "size"
  | "duplication"
  | "metadata"
  | "content"
  | "boundary"
  | "standalone"
  | "cohesion"
  | "retrieval_frequency"
  | "claim_boundary";

export interface ChunkQualityFinding {
  family: QualityFamily;
  severity: Severity;
  title: string;
  message: string;
  count: number;
  examples: string[];
}

export interface Distribution {
  count: number;
  min?: number;
  p5?: number;
  p25?: number;
  p50?: number;
  p75?: number;
  p95?: number;
  max?: number;
  mean?: number;
  stdev?: number;
  cv?: number;
}

export interface SizeFamily {
  available: boolean;
  group_field?: string | null;
  tokens?: Distribution;
  histogram?: { label: string; count: number }[];
  tiny?: number;
  tiny_pct?: number;
  giant?: number;
  giant_pct?: number;
  empty?: number;
  empty_pct?: number;
  by_group?: Record<string, { count: number; median: number; cv: number }>;
}

export interface Adjacency {
  available: boolean;
  ordered?: boolean;
  pairs?: number;
  multi_chunk_parents?: number;
  median_overlap_pct?: number;
  mean_overlap_pct?: number;
  zero_overlap_pct?: number;
  reason?: string;
}

export interface DuplicationFamily {
  available: boolean;
  exact_duplicates?: number;
  exact_duplicate_pct?: number;
  exact_clusters?: number;
  near_duplicate_pairs?: number;
  near_dup_scanned?: number;
  adjacency?: Adjacency;
}

export interface FieldReport {
  field: string;
  fill_rate: number | null;
  fill_source: "facet" | "sample";
  cardinality: number;
  cardinality_capped: boolean;
  multivalued: boolean;
  top: { value: string; count: number }[];
}

export interface MetadataFamily {
  fields: FieldReport[];
  critical: Record<string, { field: string | null; fill_rate: number | null }>;
  orphans: number;
  orphans_pct: number;
  facetable_field_count: number;
}

export interface ContentFamily {
  available: boolean;
  mojibake?: number;
  mojibake_pct?: number;
  table_heavy?: number;
  table_heavy_pct?: number;
  markup_heavy?: number;
  markup_heavy_pct?: number;
  boilerplate?: { line: string; count: number }[];
  embedding?: { field: string | null; coverage_pct: number | null };
}

export interface BoundaryFamily {
  available: boolean;
  reason?: string;
  sampled?: number;
  bad_start?: number;
  bad_start_pct?: number;
  bad_end?: number;
  bad_end_pct?: number;
  mid_table?: number;
  mid_table_pct?: number;
  mid_list?: number;
  mid_list_pct?: number;
  severed_steps?: number;
  adjacent_pairs_checked?: number;
  examples?: { chunk_id: string; issue: string; snippet: string }[];
}

export interface StandaloneFamily {
  available: boolean;
  reason?: string;
  sampled?: number;
  judged?: number;
  dependent?: number;
  dependent_pct?: number;
  examples?: { chunk_id: string; reason: string; snippet: string }[];
}

export interface CohesionFamily {
  available: boolean;
  reason?: string;
  sampled?: number;
  scored?: number;
  sentences_embedded?: number;
  smear?: Distribution;
  high_spread?: number;
  high_spread_pct?: number;
  threshold?: number;
  examples?: { chunk_id: string; smear: number; snippet: string }[];
}

export interface RetrievalFrequencyFamily {
  available: boolean;
  reason?: string;
  source?: "traces" | "probe";
  window_days?: number | null;
  events_scanned?: number;
  unique_chunks_retrieved?: number;
  sampled_chunks?: number;
  dead?: number;
  dead_pct?: number;
  hot?: number;
  hot_pct?: number;
  hot_threshold?: number;
  histogram?: { label: string; count: number }[];
  top_hot?: { chunk_id: string; count: number; title: string }[];
}

export interface ClaimBoundaryFamily {
  available: boolean;
  reason?: string;
  dataset_id?: string | null;
  cases_analyzed?: number;
  cases_skipped?: number;
  claims_total?: number;
  single_chunk?: number;
  cross_boundary?: number;
  cross_boundary_pct?: number;
  cross_adjacent?: number;
  unsupported?: number;
  examples?: { test_case_id: string; claim: string; chunk_ids: string[]; adjacent: boolean }[];
}

export interface PassUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number | null;
}

export interface ChunkQualityRunConfig {
  passes: {
    standalone: { enabled: boolean; sample_size: number };
    cohesion: { enabled: boolean; sample_size: number; max_sentences: number };
    retrieval_frequency: {
      enabled: boolean;
      source: "traces" | "probe";
      window_days: number;
      dataset_id: string | null;
      max_queries: number;
    };
    claim_boundary: { enabled: boolean; dataset_id: string | null; max_cases: number };
  };
}

export const DEFAULT_RUN_CONFIG: ChunkQualityRunConfig = {
  passes: {
    standalone: { enabled: false, sample_size: 200 },
    cohesion: { enabled: false, sample_size: 150, max_sentences: 30 },
    retrieval_frequency: {
      enabled: false,
      source: "traces",
      window_days: 30,
      dataset_id: null,
      max_queries: 100,
    },
    claim_boundary: { enabled: false, dataset_id: null, max_cases: 50 },
  },
};

export interface ChunkQualityResults {
  summary: {
    score: number;
    sample_size: number;
    total_docs: number;
    findings_total: number;
    findings_by_severity: Record<string, number>;
    critical: number;
    warn: number;
    info: number;
  };
  score: number;
  total_docs: number;
  sample_size: number;
  requested_sample: number;
  fields: {
    id: string | null;
    text: string | null;
    title: string | null;
    url: string | null;
    parent: string | null;
    ordinal: string | null;
    group: string | null;
  };
  families: {
    size: SizeFamily;
    duplication: DuplicationFamily;
    metadata: MetadataFamily;
    content: ContentFamily;
    boundary?: BoundaryFamily;
    standalone?: StandaloneFamily;
    cohesion?: CohesionFamily;
    retrieval_frequency?: RetrievalFrequencyFamily;
    claim_boundary?: ClaimBoundaryFamily;
  };
  findings: ChunkQualityFinding[];
  usage?: Record<string, PassUsage>;
}

export interface ChunkQualityRunSummary {
  id: string;
  provider_id: string;
  status: string;
  stage: string | null;
  sample_size: number;
  total_docs: number;
  processed: number;
  score: number | null;
  critical: number;
  warn: number;
  info: number;
  error: string | null;
  created_at: string;
  completed_at: string | null;
  // Per-family headline metrics lifted out of results, for cross-run trends.
  headline: Record<string, number | null>;
  config: ChunkQualityRunConfig | null;
}

export interface ChunkQualityRunDetail {
  id: string;
  provider_id: string;
  status: string;
  stage: string | null;
  sample_size: number;
  total_docs: number;
  processed: number;
  error: string | null;
  results: ChunkQualityResults | null;
  config: ChunkQualityRunConfig | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}
