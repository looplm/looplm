/**
 * Types for chunk/metadata quality runs (Data Sources → Chunk quality tab).
 * Hand-written mirror of apps/api/app/schemas/chunk_quality.py and the engine's
 * ChunkQualityReport.to_dict() (app/index_providers/chunk_quality.py).
 */

export type Severity = "info" | "warn" | "critical";
export type QualityFamily = "size" | "duplication" | "metadata" | "content";

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
  };
  findings: ChunkQualityFinding[];
}

export interface ChunkQualityRunSummary {
  id: string;
  provider_id: string;
  status: string;
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
}

export interface ChunkQualityRunDetail {
  id: string;
  provider_id: string;
  status: string;
  sample_size: number;
  total_docs: number;
  processed: number;
  error: string | null;
  results: ChunkQualityResults | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}
