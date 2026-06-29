/**
 * API functions for chunk/metadata quality runs (Data Sources page).
 */

import type {
  ChunkQualityRunDetail,
  ChunkQualityRunSummary,
} from "../api-types/chunk-quality";
import { request } from "./client";

export const startChunkQualityRun = (providerId: string, sampleSize = 8000) =>
  request<{ run_id: string; status: string }>("/api/chunk-quality/runs", {
    method: "POST",
    body: JSON.stringify({ provider_id: providerId, sample_size: sampleSize }),
  });

export const listChunkQualityRuns = (providerId: string) =>
  request<{ data: ChunkQualityRunSummary[] }>(
    `/api/chunk-quality/runs?provider_id=${encodeURIComponent(providerId)}`,
  );

export const getChunkQualityRun = (runId: string) =>
  request<ChunkQualityRunDetail>(`/api/chunk-quality/runs/${runId}`);
