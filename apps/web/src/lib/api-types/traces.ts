/**
 * Type definitions for Projects, Dashboard, Integrations, Traces,
 * Aggregate Graph, Route Analysis, and Advisor.
 *
 * Generated from the backend OpenAPI schema — do not hand-edit shapes here.
 * Regenerate with `pnpm gen:api` after changing the Pydantic schemas.
 * The CLIENT-SIDE section at the bottom has no backend schema and is hand-maintained.
 */

import type { components } from "./schema.gen";

type S = components["schemas"];

// --- Projects ---
export type Project = S["ProjectResponse"];

// --- Dashboard ---
export type DashboardStats = S["DashboardStatsResponse"];

// --- Integrations ---
export type Integration = S["IntegrationResponse"];
export type IngestKey = S["IngestKeyResponse"];
export type IngestKeyCreated = S["IngestKeyCreateResponse"];
export type CreateIntegrationBody = S["IntegrationCreate"];
export type UpdateIntegrationBody = S["IntegrationUpdate"];

// --- Traces ---
export type TraceListResponse = S["TraceListResponse"];
export type TraceListItem = S["TraceListItem"];
export type ThreadSummary = S["ThreadSummary"];
export type ThreadOrderItem = S["ThreadOrderItem"];
export type ThreadListResponse = S["ThreadListResponse"];
export type SpanNode = S["SpanResponse"];
export type TraceDetail = S["TraceDetail"];
export type TraceTreeNode = S["TraceTreeNode"];
export type TraceChildrenResponse = S["TraceChildrenResponse"];
export type TraceAnalysis = S["TraceAnalysisResponse"];

// --- Aggregate Graph ---
export type AggregateGraphNode = S["AggregateGraphNode"];
export type AggregateGraphEdge = S["AggregateGraphEdge"];
export type AggregateGraphResponse = S["AggregateGraphResponse"];

// --- Route Analysis ---
export type RouteNode = S["RouteNode"];
export type RouteEdge = S["RouteEdge"];
export type RouteAnalysisResponse = S["RouteAnalysisResponse"];
export type BottleneckNode = S["BottleneckNode"];
export type BottleneckResponse = S["BottleneckResponse"];

// --- Advisor ---
export type Suggestion = S["Suggestion"];
export type AdvisorResponse = S["AdvisorResponse"];
export type AdvisorRunResponse = S["AdvisorRunResponse"];

// --- Client-side only (no backend schema) ---

/** Free-form project settings blob; backend stores it as an open dict. */
export interface ProjectSettings {
  observe_trace_names?: string[];
  [key: string]: unknown;
}

/** Feedback score shape surfaced inline on trace payloads. */
export interface TraceFeedbackScore {
  id: string;
  score_name: string;
  value: number;
  comment?: string;
  scored_at?: string;
}

/** Progress-log entry inlined on AdvisorRunResponse — not a named API schema. */
export interface AdvisorProgressLogEntry {
  t: string;
  msg: string;
}

/** Trigger response for the async repo-aware advisor run. */
export interface AdvisorRunTrigger {
  analysis_id: string;
  status: string;
}
