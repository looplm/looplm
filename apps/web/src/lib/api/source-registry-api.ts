/**
 * API functions for the wanted-status source registry (Data Sources page).
 */

import type {
  CsvImportResult,
  GapRunDetail,
  GapRunSummary,
  SourceExpectation,
} from "../api-types/source-registry";
import { getSelectedProjectId, getToken, request } from "./client";

export const listSourceExpectations = (providerId: string) =>
  request<{ data: SourceExpectation[] }>(
    `/api/source-registry/expectations?provider_id=${encodeURIComponent(providerId)}`,
  );

export const updateSourceExpectation = (
  id: string,
  body: Partial<Pick<SourceExpectation, "name" | "html_url" | "pdf_url" | "adapter_tag" | "ack_note">>,
) =>
  request<SourceExpectation>(`/api/source-registry/expectations/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteSourceExpectation = (id: string) =>
  request<void>(`/api/source-registry/expectations/${id}`, { method: "DELETE" });

export const importSourceCsv = (providerId: string, csvText: string, replace: boolean) =>
  request<CsvImportResult>("/api/source-registry/import-csv", {
    method: "POST",
    body: JSON.stringify({ provider_id: providerId, csv_text: csvText, replace }),
  });

export const startGapRun = (providerId: string) =>
  request<{ run_id: string; status: string }>("/api/source-registry/gap-runs", {
    method: "POST",
    body: JSON.stringify({ provider_id: providerId }),
  });

export const listGapRuns = (providerId: string) =>
  request<{ data: GapRunSummary[] }>(
    `/api/source-registry/gap-runs?provider_id=${encodeURIComponent(providerId)}`,
  );

export const getGapRun = (runId: string) =>
  request<GapRunDetail>(`/api/source-registry/gap-runs/${runId}`);

export const cancelGapRun = (runId: string) =>
  request<GapRunDetail>(`/api/source-registry/gap-runs/${runId}/cancel`, {
    method: "POST",
  });

// Markdown report (text/markdown) — `request` is JSON-only, so fetch the text
// directly with the same auth/project headers.
export const fetchGapRunReport = async (runId: string): Promise<string> => {
  const headers: Record<string, string> = {};
  const token = getToken();
  const projectId = getSelectedProjectId();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (projectId) headers["X-Project-Id"] = projectId;
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/source-registry/gap-runs/${runId}/report`,
    { headers },
  );
  if (!res.ok) throw new Error(`Report not available (${res.status})`);
  return res.text();
};
