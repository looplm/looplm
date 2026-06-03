/**
 * Type definitions for Projects, Dashboard, Integrations, Traces,
 * Aggregate Graph, Route Analysis, and Advisor.
 */

// --- Projects ---

export interface ProjectSettings {
  observe_trace_names?: string[];
  [key: string]: unknown;
}

export interface Project {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  settings: ProjectSettings;
  created_at: string;
  updated_at: string;
  role?: string;
}

// --- Dashboard ---

export interface DashboardStats {
  period: { start: string; end: string };
  totals: {
    traces: number;
    failures: number;
    degraded: number;
    success: number;
    failure_rate: number;
    unique_users: number;
    unique_threads: number;
  };
  top_failures: { failure_type: string; count: number; percentage: number; example_trace_id?: string }[];
  trends: {
    date: string;
    total: number;
    failures: number;
    failure_rate: number;
    unique_users: number;
    unique_threads: number;
    feedback_positive: number;
    feedback_negative: number;
    traces_with_feedback: number;
  }[];
  fixes: { suggested: number; applied: number; dismissed: number; pending: number };
  feedback: {
    total: number;
    positive: number;
    negative: number;
    positive_rate: number;
    no_feedback_traces: number;
  };
}

// --- Integrations ---

export interface Integration {
  id: string;
  type: string;
  name: string;
  base_url?: string;
  config: Record<string, unknown>;
  sync_status: string;
  last_synced_at?: string;
  last_sync_error?: string;
  sync_progress_current?: number;
  sync_progress_total?: number;
  sync_started_at?: string;
  sync_phase?: "fetching_traces" | "processing_traces" | "fetching_scores" | "processing_scores";
  sync_message?: string;
  sync_since?: string;
  last_received_at?: string;
  created_at: string;
  updated_at: string;
}

export interface IngestKey {
  id: string;
  name: string;
  key_prefix: string;
  last_used_at?: string;
  revoked_at?: string;
  created_at: string;
}

// Returned only on creation — carries the one-time plaintext key.
export interface IngestKeyCreated extends IngestKey {
  key: string;
}

export interface CreateIntegrationBody {
  type: string;
  name: string;
  api_key: string;
  base_url?: string;
  config?: Record<string, unknown>;
}

export interface UpdateIntegrationBody {
  name?: string;
  api_key?: string;
  base_url?: string;
  config?: Record<string, unknown>;
}

// --- Traces ---

export interface TraceListResponse {
  data: TraceListItem[];
  pagination: { page: number; per_page: number; total: number; total_pages: number };
}

export interface TraceListItem {
  id: string;
  integration_id: string;
  external_id: string;
  name?: string;
  thread_id?: string;
  user_id?: string;
  parent_trace_id?: string;
  root_trace_id?: string;
  run_type?: string;
  input?: any;
  status?: string;
  duration_ms?: number;
  start_time: string;
  end_time?: string;
  error_message?: string;
  child_run_count: number;
  created_at: string;
}

export interface ThreadSummary {
  thread_id: string;
  trace_count: number;
  first_time: string;
  last_time: string;
  total_duration_ms?: number;
  has_failures: boolean;
  traces: TraceListItem[];
}

export interface ThreadOrderItem {
  type: "thread" | "trace";
  id: string;
}

export interface ThreadListResponse {
  data: ThreadSummary[];
  standalone_traces: TraceListItem[];
  order: ThreadOrderItem[];
  pagination: { page: number; per_page: number; total: number; total_pages: number };
}

export interface SpanNode {
  id: string;
  parent_span_id?: string;
  external_id?: string;
  name?: string;
  type?: string;
  input?: unknown;
  output?: unknown;
  model?: string;
  tokens_in?: number;
  tokens_out?: number;
  duration_ms?: number;
  status?: string;
  error_message?: string;
  children: SpanNode[];
}

export interface TraceDetail {
  id: string;
  integration_id: string;
  external_id: string;
  name?: string;
  thread_id?: string;
  user_id?: string;
  parent_trace_id?: string;
  root_trace_id?: string;
  run_type?: string;
  input?: unknown;
  output?: unknown;
  metadata: Record<string, unknown>;
  status?: string;
  duration_ms?: number;
  start_time: string;
  end_time?: string;
  error_message?: string;
  spans: SpanNode[];
  child_run_count: number;
  created_at: string;
}

export interface TraceTreeNode {
  id: string;
  name?: string;
  run_type?: string;
  status?: string;
  duration_ms?: number;
  start_time: string;
  end_time?: string;
  error_message?: string;
  children: TraceTreeNode[];
}

export interface TraceChildrenResponse {
  root: TraceTreeNode;
  children: TraceTreeNode[];
  total_children: number;
}

export interface TraceAnalysis {
  analysis: {
    id: string;
    trace_id: string;
    failure_type?: string;
    root_cause?: string;
    confidence?: number;
    applied: boolean;
    created_at: string;
  };
  fix_suggestions: {
    id: string;
    type: string;
    title: string;
    description?: string;
    diff?: unknown;
    status: string;
    created_at: string;
  }[];
}

export interface TraceFeedbackScore {
  id: string;
  score_name: string;
  value: number;
  comment?: string;
  scored_at?: string;
}

// --- Aggregate Graph ---

export interface AggregateGraphNode {
  id: string;
  name: string;
  run_type?: string;
  execution_count: number;
  avg_duration_ms?: number;
  failure_count: number;
  success_count: number;
}

export interface AggregateGraphEdge {
  source: string;
  target: string;
  weight: number;
}

export interface AggregateGraphResponse {
  nodes: AggregateGraphNode[];
  edges: AggregateGraphEdge[];
  total_traces_analyzed: number;
  root_node_ids: string[];
}

// --- Route Analysis ---

export interface RouteNode {
  id: string;
  name: string;
  run_type?: string;
  call_count: number;
  avg_latency_ms?: number;
  error_rate: number;
  total_duration_ms: number;
}

export interface RouteEdge {
  source: string;
  target: string;
  frequency: number;
  avg_latency_ms?: number;
}

export interface RouteAnalysisResponse {
  nodes: RouteNode[];
  edges: RouteEdge[];
  total_traces: number;
  root_node_ids: string[];
}

export interface BottleneckNode {
  node_id: string;
  name: string;
  run_type?: string;
  call_count: number;
  avg_latency_ms: number;
  error_rate: number;
  bottleneck_score: number;
  reason: string;
}

export interface BottleneckResponse {
  bottlenecks: BottleneckNode[];
  total_traces: number;
}

// --- Advisor ---

export interface Suggestion {
  title: string;
  description: string;
  category: "time_to_value" | "output_quality" | "architecture";
  impact: "high" | "medium" | "low";
  confidence: number;
  reasoning: string;
}

export interface AdvisorResponse {
  integration_id: string;
  suggestions: Suggestion[];
  analyzed_at?: string;
}

export interface AdvisorProgressLogEntry {
  t: string;
  msg: string;
}

// Poll shape for the async repo-aware advisor run.
export interface AdvisorRunResponse {
  id: string;
  integration_id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  suggestions: Suggestion[];
  error?: string | null;
  files_analyzed: string[];
  num_turns?: number | null;
  total_cost_usd?: number | null;
  repo_used: boolean;
  progress_message?: string | null;
  progress_log: AdvisorProgressLogEntry[];
  started_at?: string | null;
  completed_at?: string | null;
  analyzed_at?: string | null;
}

// Trigger response when the async repo path is used.
export interface AdvisorRunTrigger {
  analysis_id: string;
  status: string;
}
