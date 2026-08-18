/** GitHub App / Code Agent bridge endpoints. */

import { request } from "./client";

export interface GithubStatus {
  enabled: boolean;
  app_name: string | null;
  install_url: string | null;
}

export interface GithubInstallationSummary {
  installation_id: number;
  account_login: string;
  account_type: string;
}

export interface GithubRepo {
  full_name: string;
  default_branch: string;
  private: boolean;
}

export interface GithubInstallation {
  installation_id: number;
  account_login: string;
  account_type: string;
  repo_full_name: string | null;
  repo_default_branch: string | null;
  repo_branch: string | null;
}

export const getGithubStatus = () => request<GithubStatus>("/api/github/status");

export const getGithubAuthUrl = (redirectUri: string) =>
  request<{ url: string }>("/api/github/auth-url", {
    method: "POST",
    body: JSON.stringify({ redirect_uri: redirectUri }),
  });

/**
 * Finishing the browser flow returns a short-lived `grant` alongside the installations. It is
 * proof that this user controls them, and the API requires it for any installation not already
 * linked to the project, so keep it for the rest of the connect flow.
 */
export const completeGithubCallback = (code: string, state: string) =>
  request<{ installations: GithubInstallationSummary[]; grant: string }>("/api/github/callback", {
    method: "POST",
    body: JSON.stringify({ code, state }),
  });

const grantQuery = (grant?: string, separator = "?") =>
  grant ? `${separator}grant=${encodeURIComponent(grant)}` : "";

export const listInstallationRepos = (installationId: number, grant?: string) =>
  request<GithubRepo[]>(
    `/api/github/installations/${installationId}/repos${grantQuery(grant)}`,
  );

export const listRepoBranches = (
  installationId: number,
  repoFullName: string,
  grant?: string,
) =>
  request<string[]>(
    `/api/github/installations/${installationId}/branches?repo_full_name=${encodeURIComponent(repoFullName)}${grantQuery(grant, "&")}`,
  );

export const getProjectGithubInstallation = () =>
  request<GithubInstallation | null>("/api/github/installation");

export const selectProjectGithubInstallation = (
  body: {
    installation_id: number;
    account_login: string;
    account_type: string;
    repo_full_name: string;
    repo_default_branch: string | null;
    repo_branch?: string | null;
  },
  grant?: string,
) =>
  request<GithubInstallation>(`/api/github/installation${grantQuery(grant)}`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const disconnectProjectGithubInstallation = () =>
  request<void>("/api/github/installation", { method: "DELETE" });

/** Per-project GitHub App identity (the App id + OAuth client + signing key). */
export interface GithubAppConfig {
  configured: boolean;
  source: "project" | "env" | null;
  can_manage: boolean;
  app_id: string | null;
  app_name: string | null;
  client_id: string | null;
  has_client_secret: boolean;
  has_private_key: boolean;
}

export interface GithubAppConfigInput {
  app_id: string;
  app_name?: string | null;
  client_id: string;
  /** Write-only. Leave blank when updating to keep the stored value. */
  client_secret?: string;
  private_key?: string;
}

export const getProjectGithubAppConfig = () =>
  request<GithubAppConfig>("/api/github/app-config");

export const saveProjectGithubAppConfig = (body: GithubAppConfigInput) =>
  request<GithubAppConfig>("/api/github/app-config", {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteProjectGithubAppConfig = () =>
  request<void>("/api/github/app-config", { method: "DELETE" });
