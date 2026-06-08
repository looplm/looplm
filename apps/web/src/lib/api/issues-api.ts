/**
 * API client functions for the issues (signals → issues) feature.
 */

import type {
  IssueListItem,
  IssueDetail,
  IssueDetectResponse,
} from "../api-types/issues";
import { request } from "./client";

function qs(params?: Record<string, string>): string {
  if (!params) return "";
  const filtered = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== "")
  );
  const s = new URLSearchParams(filtered).toString();
  return s ? `?${s}` : "";
}

export const getIssues = (params?: Record<string, string>) =>
  request<IssueListItem[]>(`/api/issues${qs(params)}`);

export const getIssue = (id: string) =>
  request<IssueDetail>(`/api/issues/${id}`);

export const detectIssues = (days: number) =>
  request<IssueDetectResponse>(`/api/issues/detect?days=${days}`, {
    method: "POST",
  });

export const resolveIssue = (id: string) =>
  request<IssueListItem>(`/api/issues/${id}/resolve`, { method: "POST" });

export const dismissIssue = (id: string) =>
  request<IssueListItem>(`/api/issues/${id}/dismiss`, { method: "POST" });
