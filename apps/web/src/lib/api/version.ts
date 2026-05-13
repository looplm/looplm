import { request } from "./client";

export interface VersionInfo {
  api: string;
  connectors: string | null;
  commit: string | null;
}

export function getVersion(): Promise<VersionInfo> {
  return request<VersionInfo>("/api/version");
}
