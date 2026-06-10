/**
 * API functions for the read-only index explorer (Data Sources page).
 */

import type {
  IndexGroupingSuggestionResponse,
  IndexProviderOption,
  IndexSummary,
  IndexTreeResponse,
} from "../api-types/index-explorer";
import { request } from "./client";

export const getIndexExplorerProviders = () =>
  request<{ data: IndexProviderOption[] }>("/api/index-explorer/providers");

export const getIndexSummary = (providerId: string) =>
  request<IndexSummary>(
    `/api/index-explorer/summary?provider_id=${encodeURIComponent(providerId)}`,
  );

export const getIndexTree = (params: {
  providerId: string;
  groupBy: string[];
  path?: string[];
  limit?: number;
}) => {
  const q = new URLSearchParams();
  q.set("provider_id", params.providerId);
  for (const k of params.groupBy) q.append("group_by", k);
  for (const v of params.path ?? []) q.append("path", v);
  if (params.limit != null) q.set("limit", String(params.limit));
  return request<IndexTreeResponse>(`/api/index-explorer/tree?${q.toString()}`);
};

// Read the cached LLM grouping suggestion (no LLM call; suggestion may be null).
export const getGroupingSuggestion = (providerId: string) =>
  request<IndexGroupingSuggestionResponse>(
    `/api/index-explorer/grouping-suggestion?provider_id=${encodeURIComponent(providerId)}`,
  );

// Compute (and cache) a fresh grouping suggestion via the LLM advisor.
export const computeGroupingSuggestion = (providerId: string) =>
  request<IndexGroupingSuggestionResponse>("/api/index-explorer/grouping-suggestion", {
    method: "POST",
    body: JSON.stringify({ provider_id: providerId }),
  });
