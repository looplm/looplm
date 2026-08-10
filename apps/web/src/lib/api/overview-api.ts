/**
 * Overview page API client.
 *
 * Two calls: the summary (feedback + adoption + evals on one shared bucket axis) and the
 * sources breakdown. The live per-provider index reads come from index-explorer-api.
 */
import type { OverviewSummary, OverviewSummaryParams, SourcesOverview } from "../api-types";
import { cachedRequest, request } from "./client";

function buildQuery(params: OverviewSummaryParams): string {
  const qs = new URLSearchParams();
  qs.set("bucket", params.bucket);
  if (params.start_date) qs.set("start_date", params.start_date);
  if (params.end_date) qs.set("end_date", params.end_date);
  if (params.days !== undefined) qs.set("days", String(params.days));
  // "all" is the filter bar's sentinel for no environment filter, not an environment name.
  // Dropped here rather than at the call site so a caller cannot forget it.
  if (params.environment && params.environment !== "all") {
    qs.set("environment", params.environment);
  }
  // Repeated params, matching getDashboardStats and userFilterArrays. A comma-joined
  // list would be lossy: Trace.user_id is free text and may contain commas.
  for (const id of params.include_user_ids ?? []) qs.append("include_user_ids", id);
  for (const id of params.exclude_user_ids ?? []) qs.append("exclude_user_ids", id);
  return `?${qs.toString()}`;
}

/**
 * Not cached: the path carries the debounced date range, so keys would churn on every
 * filter tweak and a stale hit would show pre-change numbers.
 */
export const getOverviewSummary = (params: OverviewSummaryParams) =>
  request<OverviewSummary>(`/api/overview/summary${buildQuery(params)}`);

/**
 * Cached briefly: index state is not date-filtered and is cheap to serve slightly stale,
 * so bouncing to Data Sources and back does not refetch.
 */
export const getOverviewSources = (providerId?: string) =>
  cachedRequest<SourcesOverview>(
    providerId ? `/api/overview/sources?provider_id=${providerId}` : "/api/overview/sources",
    60_000,
  );
