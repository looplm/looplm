/**
 * Types for the Analytics page — request-type clustering + retrieval insights.
 */

export interface RequestOutcome {
  success: number;
  degraded: number;
  failure: number;
  fb_positive: number;
  fb_negative: number;
}

export interface RequestClusterTheme {
  rank: number;
  theme: string;
  count: number;
  summary_question: string;
  trace_ids: string[];
  outcome: RequestOutcome;
}

export interface RequestClustersResponse {
  id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  error?: string;
  total_requests: number;
  processed_requests: number;
  themes: RequestClusterTheme[];
  started_at?: string;
  completed_at?: string;
}

export interface RetrievalSource {
  url: string;
  domain: string;
  label: string;
  count: number;
}

export interface RetrievalActivityPoint {
  date: string;
  count: number;
  avg_latency_ms: number;
  tokens_in: number;
  tokens_out: number;
}
