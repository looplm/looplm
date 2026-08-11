/**
 * Types for synthetic question generation (Data Sources → Test questions tab).
 * Hand-written mirror of apps/api/app/schemas/synthetic_questions.py.
 */

export type SyntheticScope = "corpus" | "partition";
export type SyntheticStyle = "factual" | "paraphrase" | "negative";
export type SyntheticRunStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface SyntheticQuestionRunRequest {
  provider_id: string;
  scope: SyntheticScope;
  partition_key?: string | null;
  partition_value?: string | null;
  sample_size: number;
  questions_per_chunk: number;
  negative_share: number;
  verify_negatives: boolean;
  persist: boolean;
  dataset_id?: string | null;
  dataset_name?: string | null;
}

export interface SyntheticQuestionItem {
  text: string;
  style: SyntheticStyle;
  /** The chunk that must be retrieved for this question. Null for negatives. */
  source_chunk_id?: string | null;
  source_title?: string | null;
  source_url?: string | null;
  source_preview?: string | null;
}

export interface SyntheticQuestionCounts {
  chunks_sampled: number;
  chunks_used: number;
  /** Distinct source documents behind the run. The tell for whether a benchmark is representative. */
  documents_used?: number;
  /** Quality flag slug -> chunks it disqualified (empty, tiny, mojibake, markup_heavy, duplicate). */
  chunks_skipped: Record<string, number>;
  questions_generated: number;
  duplicates_dropped: number;
  negatives_generated: number;
  negatives_dropped: number;
  cases_created: number;
  labels_created: number;
}

export interface SyntheticQuestionResults {
  questions: SyntheticQuestionItem[];
  counts: SyntheticQuestionCounts;
  usage?: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    cost_usd: number | null;
  } | null;
}

export interface SyntheticQuestionRunSummary {
  id: string;
  provider_id: string;
  status: SyntheticRunStatus;
  stage?: string | null;
  scope: SyntheticScope;
  partition_key?: string | null;
  partition_value?: string | null;
  sample_size: number;
  questions_per_chunk: number;
  negative_share: number;
  persist: boolean;
  dataset_id?: string | null;
  dataset_name?: string | null;
  total: number;
  processed: number;
  questions_generated: number;
  cases_created: number;
  error?: string | null;
  created_at: string;
  completed_at?: string | null;
}

export interface SyntheticQuestionRunDetail {
  id: string;
  provider_id: string;
  status: SyntheticRunStatus;
  stage?: string | null;
  error?: string | null;
  scope: SyntheticScope;
  partition_key?: string | null;
  partition_value?: string | null;
  sample_size: number;
  questions_per_chunk: number;
  negative_share: number;
  verify_negatives: boolean;
  persist: boolean;
  dataset_id?: string | null;
  dataset_name?: string | null;
  total: number;
  processed: number;
  results?: SyntheticQuestionResults | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}
