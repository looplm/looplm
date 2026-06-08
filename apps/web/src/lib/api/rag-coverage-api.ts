/**
 * API functions for RAG eval-coverage: index providers + coverage runs.
 */

import type {
  AcknowledgementCreateBody,
  AnalyzeResponse,
  CoverageRun,
  IndexProvider,
  IndexProviderCreateBody,
  IndexProviderUpdateBody,
  PartitionAcknowledgement,
  PartitionKey,
  StartAnalysisBody,
  TestConnectionResult,
} from "../api-types";
import { request } from "./client";

// --- Index providers ---

export const getIndexProviders = () =>
  request<{ data: IndexProvider[] }>("/api/rag-coverage/providers");

export const createIndexProvider = (body: IndexProviderCreateBody) =>
  request<IndexProvider>("/api/rag-coverage/providers", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateIndexProvider = (id: string, body: IndexProviderUpdateBody) =>
  request<IndexProvider>(`/api/rag-coverage/providers/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteIndexProvider = (id: string) =>
  request<void>(`/api/rag-coverage/providers/${id}`, { method: "DELETE" });

export const testIndexProvider = (id: string) =>
  request<TestConnectionResult>(`/api/rag-coverage/providers/${id}/test`, {
    method: "POST",
  });

export const getPartitionKeys = (providerId: string) =>
  request<{ data: PartitionKey[] }>(
    `/api/rag-coverage/providers/${providerId}/partition-keys`,
  );

// --- Coverage runs ---

export const startCoverageAnalysis = (body: StartAnalysisBody) =>
  request<AnalyzeResponse>("/api/rag-coverage/analyze", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getCoverageRun = (runId: string) =>
  request<CoverageRun>(`/api/rag-coverage/runs/${runId}`);

export const listCoverageRuns = () =>
  request<{ data: CoverageRun[] }>("/api/rag-coverage/runs");

// --- Acknowledgements (partition-quality memory) ---

export const getAcknowledgements = (providerId: string, partitionKey: string) =>
  request<{ data: PartitionAcknowledgement[] }>(
    `/api/rag-coverage/acknowledgements?provider_id=${encodeURIComponent(
      providerId,
    )}&partition_key=${encodeURIComponent(partitionKey)}`,
  );

export const createAcknowledgement = (body: AcknowledgementCreateBody) =>
  request<PartitionAcknowledgement>("/api/rag-coverage/acknowledgements", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const deleteAcknowledgement = (id: string) =>
  request<void>(`/api/rag-coverage/acknowledgements/${id}`, { method: "DELETE" });
