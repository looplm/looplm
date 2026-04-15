/**
 * Type definitions for Prompts, Feedback, and Test Datasets.
 */

// --- Prompts ---

export interface PromptItem {
  id: string;
  integration_id: string;
  external_id: string;
  name: string;
  template: string;
  version: number;
  variables: string[];
  metadata: Record<string, unknown>;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface PromptListResponse {
  data: PromptItem[];
  total: number;
}

export interface AntiPattern {
  pattern: string;
  description: string;
  severity: string;
  location: string;
}

export interface PromptReviewResult {
  id: string;
  prompt_id: string;
  anti_patterns: AntiPattern[];
  suggestions: string[];
  rewritten_prompt: string;
  reviewed_at?: string;
  model?: string;
}

export interface PromptReviewListResponse {
  data: PromptReviewResult[];
  total: number;
}

// --- Feedback ---

export interface FeedbackScoreItem {
  id: string;
  trace_id?: string;
  external_trace_id: string;
  score_name: string;
  value: number;
  data_type: string;
  comment?: string;
  scored_at?: string;
  created_at: string;
  trace_input?: any;
  trace_output?: any;
  trace_status?: string;
  trace_start_time?: string;
  trace_name?: string;
  trace_metadata?: Record<string, unknown>;
  eval_verdict?: string;
  eval_reasoning?: string;
  eval_confidence?: number;
}

export interface FeedbackListResponse {
  data: FeedbackScoreItem[];
  pagination: { page: number; per_page: number; total: number; total_pages: number };
}

export interface FeedbackTrend {
  date: string;
  positive: number;
  negative: number;
  total: number;
}

export interface GraderStats {
  name: string;
  total: number;
  passed: number;
  failed: number;
  pass_rate: number;
}

export interface GraderTrend {
  date: string;
  passed: number;
  failed: number;
  total: number;
}

export interface FeedbackStatsResponse {
  total_feedback: number;
  positive: number;
  negative: number;
  no_feedback_traces: number;
  positive_rate: number;
  trends: FeedbackTrend[];
  grader_stats: GraderStats[];
  grader_trends: Record<string, GraderTrend[]>;
}

export interface FeedbackScoreDetail extends FeedbackScoreItem {
  trace_metadata: Record<string, unknown>;
  trace_duration_ms?: number;
  trace_error_message?: string;
}

// --- Feedback Evaluation ---

export interface FeedbackEvalItem {
  feedback_id: string;
  trace_id?: string;
  score_name: string;
  value: number;
  comment?: string;
  trace_input_preview?: string;
  verdict: string;
  reasoning: string;
  confidence: number;
}

export interface FeedbackEvalSummary {
  total_count: number;
  evaluated_count: number;
  suspicious_count: number;
  helpful_count: number;
  unhelpful_count: number;
  verdict_counts: Record<string, number>;
}

export interface FeedbackEvaluateResponse {
  id: string;
  status: "pending" | "running" | "completed" | "failed";
  error?: string;
  summary: FeedbackEvalSummary;
  items: FeedbackEvalItem[];
  started_at?: string;
  completed_at?: string;
}

export interface FeedbackEvaluatorConfig {
  id: string;
  prompt: string;
  verdicts: string[];
  default_verdict: string;
  model: string | null;
  created_at: string;
  updated_at: string;
}

// --- Top Questions Analysis ---

export interface TopQuestionItem {
  question: string;
  feedback_value: number | null;
  trace_id: string | null;
}

export interface TopQuestionTheme {
  rank: number;
  theme: string;
  count: number;
  summary_question: string;
  all_questions: TopQuestionItem[];
  feedback_sentiment: { positive: number; negative: number };
}

export interface TopQuestionsResponse {
  id: string;
  status: "pending" | "running" | "completed" | "failed";
  error?: string;
  total_questions: number;
  processed_questions: number;
  themes: TopQuestionTheme[];
  started_at?: string;
  completed_at?: string;
}

// --- Test Datasets ---

export interface TestDatasetItem {
  id: string;
  name: string;
  description: string | null;
  tags: string[];
  test_count: number;
  created_at: string;
  updated_at: string;
}

export interface TestDatasetListResponse {
  data: TestDatasetItem[];
  pagination: { page: number; per_page: number; total: number; total_pages: number };
}

export interface TestCaseItem {
  id: string;
  dataset_id: string;
  test_id: string;
  prompt: string;
  expected_answer: string | null;
  expected_sources: string[];
  context_filters: Record<string, string>;
  team_filter: string[];
  tag_filter: string[];
  message_count: number | null;
  has_summary: boolean;
  folder: string | null;
  document: string | null;
  expected_page_urls: string[];
  expected_source_types: string[];
  max_answer_length: number | null;
  source_feedback_id: string | null;
  source_trace_id: string | null;
  tags: string[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface TestDatasetDetail extends TestDatasetItem {
  test_cases: TestCaseItem[];
}

export interface TestCaseSuggestion {
  feedback_id: string;
  trace_id: string | null;
  feedback_value: number;
  prompt: string;
  actual_answer: string | null;
  suggested_expected_answer: string | null;
  context_filters: Record<string, string>;
  team_filter: string[];
  tag_filter: string[];
  message_count: number | null;
  has_summary: boolean;
  scored_at: string | null;
  comment: string | null;
  suggested_dataset_id: string | null;
}

export interface TestCaseCreateBody {
  test_id: string;
  prompt: string;
  expected_answer?: string;
  expected_sources?: string[];
  context_filters?: Record<string, string>;
  team_filter?: string[];
  tag_filter?: string[];
  message_count?: number;
  has_summary?: boolean;
  folder?: string;
  document?: string;
  expected_page_urls?: string[];
  expected_source_types?: string[];
  max_answer_length?: number | null;
  source_feedback_id?: string;
  source_trace_id?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

// --- Import History ---

export interface JsonImportItem {
  id: string;
  entity_type: string;
  filename: string;
  record_count: number;
  status: string;
  error_message: string | null;
  created_at: string;
}

export interface JsonImportListResponse {
  data: JsonImportItem[];
  pagination: { page: number; per_page: number; total: number; total_pages: number };
}

export interface TestDatasetExport {
  name: string;
  description: string | null;
  testCases: {
    id: string;
    prompt: string;
    expectedAnswer: string | null;
    expectedSources: string[];
    teamFilter: string[];
    tagFilter: string[];
    filters: Record<string, string>;
    folder: string | null;
    document: string | null;
    expectedPageUrls: string[];
    expectedSourceTypes: string[];
    maxAnswerLength: number | null;
    metadata?: Record<string, unknown>;
  }[];
}
