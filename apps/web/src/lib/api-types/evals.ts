/**
 * Type definitions for Evaluations, Eval Trigger, and Evaluators.
 */

// --- Evaluations ---

export interface GraderSummaryItem {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  pass_rate: number;
}

export interface ScoreSummaryItem {
  count: number;
  avg: number;
  min: number;
  max: number;
}

export interface EvalRunListItem {
  id: string;
  name: string;
  source?: string;
  tags: string[];
  total: number;
  passed: number;
  failed: number;
  pass_rate: number;
  grader_summary: Record<string, GraderSummaryItem>;
  score_summary: Record<string, ScoreSummaryItem>;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface EvalRunListResponse {
  data: EvalRunListItem[];
  pagination: { page: number; per_page: number; total: number; total_pages: number };
}

export interface EvalGraderResult {
  pass: boolean;
  reason?: string;
  skipped?: boolean;
  details?: Record<string, unknown>;
}

export interface ConversationTurn {
  turn: number;
  prompt: string;
  response: string | null;
  pass: boolean;
  error?: string;
  graders: Record<string, { pass: boolean; reason?: string; skipped?: boolean }>;
}

export interface EvalResultItem {
  id: string;
  test_id: string;
  pass: boolean;
  reason?: string;
  input?: string;
  output?: string;
  expected_output?: string;
  tags: string[];
  graders: Record<string, EvalGraderResult>;
  scores: Record<string, number>;
  metadata: Record<string, unknown> & { conversation_history?: ConversationTurn[] };
  turns_to_pass?: number | null;
  created_at: string;
}

export interface EvalRunDetail {
  id: string;
  name: string;
  source?: string;
  tags: string[];
  total: number;
  passed: number;
  failed: number;
  pass_rate: number;
  grader_summary: Record<string, GraderSummaryItem>;
  score_summary: Record<string, ScoreSummaryItem>;
  metadata: Record<string, unknown>;
  created_at: string;
  results: EvalResultItem[];
}

export interface EvalRunStats {
  total: number;
  passed: number;
  failed: number;
  pass_rate: number;
  grader_summary: Record<string, GraderSummaryItem>;
  score_summary: Record<string, ScoreSummaryItem>;
}

// --- Eval Trigger ---

export interface DatasetPickerItem {
  id: string;
  name: string;
  test_count: number;
}

export interface DatasetPickerResponse {
  datasets: DatasetPickerItem[];
}

export interface EvalJobConfig {
  filter_mode?: "as_configured" | "no_filters" | "both";
  concurrency?: number;
  max_turns?: number;
  use_batch?: boolean;
}

export interface EvalJob {
  id: string;
  project_id: string;
  test_suite: string;
  dataset_ids?: string[];
  status: "pending" | "running" | "batch_pending" | "completed" | "failed" | "cancelled";
  run_id?: string;
  batch_eval_job_id?: string;
  error?: string;
  log?: string;
  config: EvalJobConfig;
  progress_current?: number;
  progress_total?: number;
  started_at: string;
  completed_at?: string;
}

export interface EvalJobLogsResponse {
  log: string;
  total_lines: number;
}

export interface EvalJobListResponse {
  data: EvalJob[];
}

export interface TriggerEvalResponse {
  job_id: string;
  status: string;
}

// --- Evaluators ---

export interface EvaluatorItem {
  id: string;
  name: string;
  display_name: string | null;
  type: "llm_judge" | "deterministic" | "hybrid";
  description: string | null;
  relevance: "core" | "important" | "minor";
  affects_pass: boolean;
  config: Record<string, unknown>;
  source: string | null;
  enabled: boolean;
  total_evaluations: number;
  pass_rate: number | null;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface EvaluatorListResponse {
  data: EvaluatorItem[];
  total: number;
}

export interface EvaluatorCreateBody {
  name: string;
  display_name?: string;
  type: string;
  description?: string;
  relevance?: string;
  affects_pass?: boolean;
  config?: Record<string, unknown>;
  source?: string;
}

export interface EvaluatorUpdateBody {
  display_name?: string;
  description?: string;
  relevance?: string;
  affects_pass?: boolean;
  config?: Record<string, unknown>;
  enabled?: boolean;
  source?: string;
}

// --- Eval Report ---

export interface ReportTraceInfo {
  tool_calls_count: number;
  tools_used: string[];
  token_usage?: Record<string, number> | null;
  raw_response_excerpt?: string | null;
}

export interface ReportGraderEntry {
  reason?: string | null;
}

export interface ReportPreconditions {
  filter_mode?: string;
  team_filter?: string[];
  tag_filter?: string[];
  context_filters?: Record<string, unknown>;
}

export interface ReportTestCaseDetail {
  test_id: string;
  pass: boolean;
  input?: string | null;
  output?: string | null;
  expected_output?: string | null;
  failed_graders: Record<string, ReportGraderEntry>;
  passed_graders: Record<string, ReportGraderEntry>;
  skipped_graders: Record<string, ReportGraderEntry>;
  scores: Record<string, number>;
  trace: ReportTraceInfo;
  preconditions?: ReportPreconditions | null;
}

export interface ReportGraderFailure {
  fail_count: number;
  affects_pass: boolean;
  common_issues: string[];
  failed_test_ids: string[];
}

export interface ReportFailureAnalysis {
  by_grader: Record<string, ReportGraderFailure>;
  by_test_case: ReportTestCaseDetail[];
}

export interface ReportSummary {
  total: number;
  passed: number;
  failed: number;
  pass_rate: number;
  grader_summary: Record<string, GraderSummaryItem>;
  score_summary: Record<string, ScoreSummaryItem>;
}

export interface ReportEvalRunInfo {
  id: string;
  name: string;
  created_at?: string | null;
  source?: string | null;
}

export interface EvalReportResponse {
  eval_run: ReportEvalRunInfo;
  summary: ReportSummary;
  failure_analysis: ReportFailureAnalysis;
  recommendations: string[];
}

// --- Multi-Run Report ---

export interface MultiRunReportResponse {
  id?: string;
  markdown: string;
  run_count: number;
  total_tests: number;
}

// --- Saved Reports ---

export interface EvalReportListItem {
  id: string;
  title: string;
  report_type: string;
  run_ids: string[];
  run_count: number;
  total_tests: number;
  created_at: string;
}

export interface EvalReportListResponse {
  data: EvalReportListItem[];
  pagination: { page: number; per_page: number; total: number; total_pages: number };
}

export interface EvalReportDetail {
  id: string;
  title: string;
  report_type: string;
  markdown: string;
  run_ids: string[];
  run_count: number;
  total_tests: number;
  created_at: string;
}

// --- Experiments ---

export interface Experiment {
  id: string;
  name: string;
  description: string | null;
  variables: Record<string, string>;
  created_at: string;
  updated_at: string;
}

export interface ExperimentListResponse {
  data: Experiment[];
}

export interface ExperimentCreateBody {
  name: string;
  description?: string;
  variables: Record<string, string>;
}

export interface ExperimentUpdateBody {
  name?: string;
  description?: string;
  variables?: Record<string, string>;
}

// --- Eval Sessions ---

export interface EvalSession {
  id: string;
  project_id: string;
  name: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  dataset_ids: string[] | null;
  experiment_ids: string[];
  config: Record<string, unknown>;
  progress_current: number | null;
  progress_total: number | null;
  run_ids: string[];
  started_at: string;
  completed_at: string | null;
}

export interface EvalSessionListResponse {
  data: EvalSession[];
}

export interface TriggerSessionResponse {
  session_id: string;
  experiment_count: number;
  status: string;
}

// --- Code Agent (Eval-driven code suggestions) ---

export interface CodeSuggestionItem {
  id: string;
  type: string;
  title: string;
  description: string | null;
  file_path: string | null;
  line_start: number | null;
  line_end: number | null;
  diff: { before: string; after: string } | null;
  impact: string | null;
  confidence: number | null;
  reasoning: string | null;
  related_test_ids: string[];
  status: string;
  created_at: string;
}

export interface OpenCodeAnalysisResponse {
  id: string;
  eval_run_id: string;
  status: string;
  error: string | null;
  files_analyzed: string[];
  failure_summary: string | null;
  suggestion_count: number;
  suggestions: CodeSuggestionItem[];
  total_cost_usd: number | null;
  num_turns: number | null;
  analysis_mode: string | null;
  progress_message: string | null;
  progress_log: { t: string; msg: string }[];
  started_at: string | null;
  completed_at: string | null;
}
