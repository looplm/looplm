/**
 * API functions for the read-only index explorer (Data Sources page).
 */

import type {
  IndexChunkMetadataResponse,
  IndexFileChunksResponse,
  IndexFileListResponse,
  IndexFileTypesResponse,
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
  // Ordered levels; each inner array is the field(s) at that level (parallel).
  levels: string[][];
  // (field, value) pairs already drilled into, one per descended level.
  path?: { key: string; value: string }[];
  limit?: number;
}) => {
  const q = new URLSearchParams();
  q.set("provider_id", params.providerId);
  for (const lvl of params.levels) q.append("level", lvl.join(","));
  for (const p of params.path ?? []) {
    q.append("path_key", p.key);
    q.append("path_value", p.value);
  }
  if (params.limit != null) q.set("limit", String(params.limit));
  return request<IndexTreeResponse>(`/api/index-explorer/tree?${q.toString()}`);
};

// --- Files tab: file-type overview + filename search → chunks-of-a-file ---

// The file/content types present in the index, with counts (field=null if none).
export const getIndexFileTypes = (providerId: string) =>
  request<IndexFileTypesResponse>(
    `/api/index-explorer/file-types?provider_id=${encodeURIComponent(providerId)}`,
  );

// Distinct files (attachments + pages) whose filename/title matches the query.
export const searchIndexFiles = (params: {
  providerId: string;
  q: string;
  limit?: number;
}) => {
  const qs = new URLSearchParams({ provider_id: params.providerId, q: params.q });
  if (params.limit != null) qs.set("limit", String(params.limit));
  return request<IndexFileListResponse>(`/api/index-explorer/files?${qs.toString()}`);
};

// Every chunk of one file, in reading order.
export const getIndexFileChunks = (params: {
  providerId: string;
  fileKey: string;
  fileValue: string;
  kind: string;
  label?: string;
  limit?: number;
}) => {
  const qs = new URLSearchParams({
    provider_id: params.providerId,
    file_key: params.fileKey,
    file_value: params.fileValue,
    kind: params.kind,
  });
  if (params.label != null) qs.set("label", params.label);
  if (params.limit != null) qs.set("limit", String(params.limit));
  return request<IndexFileChunksResponse>(
    `/api/index-explorer/file-chunks?${qs.toString()}`,
  );
};

// All index fields for one chunk (embedding vectors omitted).
export const getIndexChunkMetadata = (providerId: string, chunkId: string) => {
  const qs = new URLSearchParams({ provider_id: providerId, chunk_id: chunkId });
  return request<IndexChunkMetadataResponse>(
    `/api/index-explorer/chunk-metadata?${qs.toString()}`,
  );
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
