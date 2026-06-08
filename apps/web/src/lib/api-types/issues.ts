/**
 * Type definitions for the issues (signals → issues) feature.
 */

export type IssueStatus =
  | "open"
  | "diagnosing"
  | "resolving"
  | "resolved"
  | "recurring"
  | "dismissed";

export type IssueSeverity = "high" | "medium" | "low";

export interface IssueListItem {
  id: string;
  title: string;
  category: string | null;
  severity: string;
  status: string;
  signal_types: string[];
  trace_count: number;
  affected_pct: number | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

export interface IssueEvidenceItem {
  trace_id: string | null;
  signal_type: string;
  detail: string | null;
  occurred_at: string | null;
}

export interface IssueEventItem {
  event_type: string;
  detail: Record<string, unknown> | null;
  created_at: string;
}

export interface IssueDetail extends IssueListItem {
  description: string | null;
  root_cause: string | null;
  suggested_fix: string | null;
  integration_id: string | null;
  created_at: string;
  updated_at: string;
  evidence: IssueEvidenceItem[];
  events: IssueEventItem[];
}

export interface IssueDetectResponse {
  signals: number;
  issues_created: number;
  issues_updated: number;
  issues_diagnosed: number;
  used_llm: boolean;
}
