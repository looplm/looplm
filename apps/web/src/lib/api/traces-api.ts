/**
 * API functions for Dashboard, Integrations, Traces, Fixes, Graph,
 * Route Analysis, and Advisor.
 */

import type {
  DashboardStats,
  Integration,
  CreateIntegrationBody,
  UpdateIntegrationBody,
  IngestKey,
  IngestKeyCreated,
  TraceListResponse,
  ThreadListResponse,
  TraceDetail,
  RagPipelineView,
  TraceChildrenResponse,
  TraceAnalysis,
  TraceFeedbackScore,
  AggregateGraphResponse,
  RouteAnalysisResponse,
  BottleneckResponse,
  AdvisorResponse,
  AdvisorRunResponse,
  AdvisorRunTrigger,
} from "../api-types";
import { cachedRequest, invalidateCache, request } from "./client";

// --- Dashboard ---

export const getDashboardStats = (
  params: { days?: number; start_date?: string; end_date?: string; environment?: string; include_user_ids?: string[]; exclude_user_ids?: string[] } = {}
) => {
  const qs = new URLSearchParams();
  if (params.start_date) qs.set("start_date", params.start_date);
  if (params.end_date) qs.set("end_date", params.end_date);
  if (!params.start_date) qs.set("days", String(params.days ?? 7));
  if (params.environment && params.environment !== "all") qs.set("environment", params.environment);
  if (params.include_user_ids?.length) {
    for (const uid of params.include_user_ids) qs.append("include_user_ids", uid);
  }
  if (params.exclude_user_ids?.length) {
    for (const uid of params.exclude_user_ids) qs.append("exclude_user_ids", uid);
  }
  return request<DashboardStats>(`/api/dashboard/stats?${qs.toString()}`);
};

// --- Integrations ---

export const getIntegrations = () =>
  request<{ data: Integration[] }>("/api/integrations");

export const createIntegration = (body: CreateIntegrationBody) =>
  request<Integration>("/api/integrations", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateIntegration = (id: string, body: UpdateIntegrationBody) =>
  request<Integration>(`/api/integrations/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteIntegration = (id: string) =>
  request<void>(`/api/integrations/${id}`, { method: "DELETE" });

export const triggerSync = async (id: string, body?: { since?: string; update_existing?: boolean }) => {
  const result = await request<{ message: string }>(`/api/integrations/${id}/sync`, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });
  invalidateCache("/api/route-analysis/");
  return result;
};

export const stopSync = (id: string) =>
  request<{ message: string }>(`/api/integrations/${id}/sync/stop`, { method: "POST" });

// --- Ingest keys (first-party tracing) ---

export const getIngestKeys = (integrationId: string) =>
  request<{ data: IngestKey[] }>(`/api/integrations/${integrationId}/ingest-keys`);

export const createIngestKey = (integrationId: string, name: string) =>
  request<IngestKeyCreated>(`/api/integrations/${integrationId}/ingest-keys`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });

export const revokeIngestKey = (integrationId: string, keyId: string) =>
  request<void>(`/api/integrations/${integrationId}/ingest-keys/${keyId}`, { method: "DELETE" });

// --- Traces ---

export const getTraceEnvironments = () =>
  request<string[]>("/api/traces/environments");

export const getTraceUsers = () =>
  request<{ user_id: string; username: string | null }[]>("/api/traces/users");

export const getTraceNames = () =>
  request<string[]>("/api/traces/names");

export const getTraceThreadIds = () =>
  request<string[]>("/api/traces/thread-ids");

export const getTraceStatuses = () =>
  request<string[]>("/api/traces/statuses");

export const getTraces = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<TraceListResponse>(`/api/traces${qs}`);
};

export const getThreads = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<ThreadListResponse>(`/api/traces/threads${qs}`);
};

export const getTrace = (id: string) => request<TraceDetail>(`/api/traces/${id}`);

export const getTraceChildren = (id: string) =>
  request<TraceChildrenResponse>(`/api/traces/${id}/children`);

export const getTraceAnalysis = (id: string) =>
  request<TraceAnalysis>(`/api/traces/${id}/analysis`);

export const getTraceFeedback = (id: string) =>
  request<TraceFeedbackScore[]>(`/api/traces/${id}/feedback`);

export const getTraceRagPipeline = (id: string) =>
  request<RagPipelineView>(`/api/traces/${id}/rag-pipeline`);

export const triggerAnalysis = (id: string) =>
  request<{ message: string; analysis_id: string }>(`/api/traces/${id}/analyze`, {
    method: "POST",
  });

// --- Fixes ---

export const applyFix = (id: string) =>
  request<{ id: string; status: string }>(`/api/fixes/${id}/apply`, { method: "POST" });

// --- Graph ---

export const getAggregateGraph = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<AggregateGraphResponse>(`/api/graph/aggregate${qs}`);
};

// --- Route Analysis ---

export const getRouteAnalysis = (integrationId: string) =>
  cachedRequest<RouteAnalysisResponse>(`/api/route-analysis/${integrationId}`, 5 * 60_000);

export const getRouteBottlenecks = (integrationId: string) =>
  request<BottleneckResponse>(`/api/route-analysis/${integrationId}/bottlenecks`);

// --- Advisor ---

// Graph-only path (use_repo=false) returns AdvisorResponse; repo path returns a
// pending trigger (202) that the caller polls via getAdvisorRun.
export const triggerAdvisorAnalysis = (
  integrationId: string,
  extraContext = "",
  useRepo = false,
) =>
  request<AdvisorResponse | AdvisorRunTrigger>(`/api/advisor/${integrationId}/analyze`, {
    method: "POST",
    body: JSON.stringify({ extra_context: extraContext, use_repo: useRepo }),
  });

export const getAdvisorSuggestions = (integrationId: string) =>
  request<AdvisorResponse>(`/api/advisor/${integrationId}/suggestions`);

export const getAdvisorRun = (integrationId: string) =>
  request<AdvisorRunResponse>(`/api/advisor/${integrationId}/run`);

export const cancelAdvisorRun = (integrationId: string) =>
  request<{ status: string; analysis_id: string }>(`/api/advisor/${integrationId}/cancel`, {
    method: "POST",
  });
