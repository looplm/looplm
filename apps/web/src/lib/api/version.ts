import { request } from "./client";

export interface VersionInfo {
  api: string;
  connectors: string | null;
  commit: string | null;
}

export interface LatestRelease {
  tag: string | null;
  name: string | null;
  published_at: string | null;
  html_url: string | null;
  body: string | null;
}

export interface LatestVersionInfo {
  enabled: boolean;
  running: string;
  latest: LatestRelease | null;
  error: string | null;
}

export function getVersion(): Promise<VersionInfo> {
  return request<VersionInfo>("/api/version");
}

export function getLatestVersion(): Promise<LatestVersionInfo> {
  return request<LatestVersionInfo>("/api/version/latest");
}
