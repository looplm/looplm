/**
 * API functions for Datasets and Test Cases.
 */

import type {
  TestDatasetItem,
  TestDatasetListResponse,
  TestCaseItem,
  TestDatasetDetail,
  TestCaseSuggestion,
  TestCaseCreateBody,
  TestCaseUpdateBody,
  TestDatasetExport,
  DuplicatesResponse,
} from "../api-types";
import { request } from "./client";

// --- Datasets ---

export const getDatasets = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<TestDatasetListResponse>(`/api/datasets${qs}`);
};

export const createDataset = (body: { name: string; description?: string; tags?: string[] }) =>
  request<TestDatasetItem>("/api/datasets", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getDataset = (id: string) =>
  request<TestDatasetDetail>(`/api/datasets/${id}`);

export const updateDataset = (id: string, body: { name?: string; description?: string; tags?: string[] }) =>
  request<TestDatasetItem>(`/api/datasets/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteDataset = (id: string) =>
  request<void>(`/api/datasets/${id}`, { method: "DELETE" });

export const bulkDeleteDatasets = (ids: string[]) =>
  Promise.all(ids.map((id) => deleteDataset(id)));

export const createTestCase = (datasetId: string, body: TestCaseCreateBody) =>
  request<TestCaseItem>(`/api/datasets/${datasetId}/cases`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateTestCase = (datasetId: string, caseId: string, body: TestCaseUpdateBody) =>
  request<TestCaseItem>(`/api/datasets/${datasetId}/cases/${caseId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteTestCase = (datasetId: string, caseId: string) =>
  request<void>(`/api/datasets/${datasetId}/cases/${caseId}`, { method: "DELETE" });

/** A test case's current expected_page_urls, looked up by test_id. */
export interface ExpectedUrlsResponse {
  test_id: string;
  expected_page_urls: string[];
}

/** Fetch a test case's current expected_page_urls, keyed by test_id (variant suffix tolerated). */
export const getExpectedUrls = (datasetId: string, testId: string) =>
  request<ExpectedUrlsResponse>(
    `/api/datasets/${datasetId}/cases/expected-urls?test_id=${encodeURIComponent(testId)}`,
  );

/** Append URLs to a test case's expected_page_urls (deduped server-side), keyed by test_id. */
export const addExpectedUrls = (datasetId: string, testId: string, urls: string[]) =>
  request<TestCaseItem>(`/api/datasets/${datasetId}/cases/expected-urls`, {
    method: "POST",
    body: JSON.stringify({ test_id: testId, urls }),
  });

export const exportDataset = (id: string) =>
  request<TestDatasetExport>(`/api/datasets/${id}/export`);

export const importDataset = (body: { name?: string; description?: string; testCases: unknown[]; filename?: string }) =>
  request<TestDatasetItem>("/api/datasets/import", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getTestCaseSuggestions = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<TestCaseSuggestion[]>(`/api/datasets/suggestions${qs}`);
};

// --- Duplicate detection ---

export const getDuplicates = (params?: { threshold?: number; scope?: string }) => {
  const qs = new URLSearchParams();
  if (params?.threshold != null) qs.set("threshold", String(params.threshold));
  if (params?.scope) qs.set("scope", params.scope);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request<DuplicatesResponse>(`/api/datasets/duplicates${suffix}`);
};

/** Merge redundant cases into one and delete the merged ones. */
export const mergeDuplicates = (keepCaseId: string, mergeCaseIds: string[]) =>
  request<TestCaseItem>("/api/datasets/duplicates/merge", {
    method: "POST",
    body: JSON.stringify({ keep_case_id: keepCaseId, merge_case_ids: mergeCaseIds }),
  });

/** Record a set of cases as mutually non-duplicate so they stop resurfacing. */
export const dismissDuplicates = (caseIds: string[]) =>
  request<void>("/api/datasets/duplicates/dismiss", {
    method: "POST",
    body: JSON.stringify({ case_ids: caseIds }),
  });
