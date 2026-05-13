/**
 * Core HTTP client, auth, and project management.
 */

import type { Project } from "../api-types";

// Same-origin by default — Nginx (prod) and next.config.ts rewrites (dev) route /api/*
// to the API. Absolute overrides still work if NEXT_PUBLIC_API_URL is explicitly set.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// --- Auth token management ---

const TOKEN_KEY = "looplm_token";
const REFRESH_TOKEN_KEY = "looplm_refresh_token";
const EXPIRES_AT_KEY = "looplm_expires_at";

/** Minimum remaining lifetime (ms) before we proactively refresh. */
const REFRESH_MARGIN_MS = 5 * 60 * 1000;

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(
  accessToken: string,
  refreshToken?: string,
  expiresIn?: number,
): void {
  localStorage.setItem(TOKEN_KEY, accessToken);
  if (refreshToken) {
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  }
  if (expiresIn) {
    localStorage.setItem(EXPIRES_AT_KEY, String(Date.now() + expiresIn * 1000));
  }
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(EXPIRES_AT_KEY);
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

function getExpiresAt(): number | null {
  if (typeof window === "undefined") return null;
  const v = localStorage.getItem(EXPIRES_AT_KEY);
  return v ? Number(v) : null;
}

function isTokenExpiringSoon(): boolean {
  const expiresAt = getExpiresAt();
  if (!expiresAt) return false;
  return Date.now() + REFRESH_MARGIN_MS >= expiresAt;
}

let refreshPromise: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  const rt = getRefreshToken();
  if (!rt) return false;

  try {
    const res = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: rt }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    setToken(data.access_token, data.refresh_token, data.expires_in);
    return true;
  } catch {
    return false;
  }
}

/** Deduplicated refresh — multiple concurrent callers share one request. */
function ensureRefreshed(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

// --- Project selection ---

export function getSelectedProjectId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("looplm_project_id");
}

export function setSelectedProjectId(id: string): void {
  localStorage.setItem("looplm_project_id", id);
}

export function clearSelectedProjectId(): void {
  localStorage.removeItem("looplm_project_id");
}

// --- HTTP client ---

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  // Proactive refresh: if the access token is about to expire, refresh first
  if (isTokenExpiringSoon() && getRefreshToken()) {
    await ensureRefreshed();
  }

  const doFetch = async () => {
    const token = getToken();
    const projectId = getSelectedProjectId();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options?.headers as Record<string, string>),
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    if (projectId) {
      headers["X-Project-Id"] = projectId;
    }
    return fetch(`${API_BASE}${path}`, { ...options, headers });
  };

  let res = await doFetch();

  // On 401, attempt a token refresh and retry once
  if (res.status === 401 && getRefreshToken()) {
    const refreshed = await ensureRefreshed();
    if (refreshed) {
      res = await doFetch();
    }
  }

  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body?.detail;
    const errorObj = body?.error || (typeof detail === "object" && detail !== null ? detail.error : null);
    const code = errorObj?.code || res.status;
    const message = errorObj?.message || (typeof detail === "string" ? detail : null) || res.statusText || "Unknown error";
    throw new Error(`[${code}] ${message}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// --- Cached GET requests ---

const globalCache = globalThis as unknown as { __apiCache?: Map<string, { data: unknown; ts: number }> };
if (!globalCache.__apiCache) globalCache.__apiCache = new Map();
const cache = globalCache.__apiCache;

export async function cachedRequest<T>(path: string, ttlMs = 30_000): Promise<T> {
  const key = `${getSelectedProjectId()}:${path}`;
  const hit = cache.get(key);
  if (hit && Date.now() - hit.ts < ttlMs) return hit.data as T;
  const data = await request<T>(path);
  cache.set(key, { data, ts: Date.now() });
  return data;
}

export function invalidateCache(pathPrefix?: string): void {
  if (!pathPrefix) { cache.clear(); return; }
  for (const key of cache.keys()) {
    if (key.includes(pathPrefix)) cache.delete(key);
  }
}

// --- Auth ---

interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  token_type: string;
}

export const login = async (email: string, password: string) => {
  const data = await request<TokenResponse>(
    "/api/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) }
  );
  setToken(data.access_token, data.refresh_token, data.expires_in);
  return data;
};

export const register = async (email: string, password: string, inviteToken?: string) => {
  const body: Record<string, string> = { email, password };
  if (inviteToken) body.invite_token = inviteToken;
  const data = await request<TokenResponse>(
    "/api/auth/register",
    { method: "POST", body: JSON.stringify(body) }
  );
  setToken(data.access_token, data.refresh_token, data.expires_in);
  return data;
};

export const logout = () => {
  clearToken();
  clearSelectedProjectId();
  if (typeof window !== "undefined") {
    window.location.href = "/login";
  }
};

// --- Projects ---

export const getProjects = () =>
  request<{ data: Project[] }>("/api/projects");

export const createProject = (body: { name: string; description?: string }) =>
  request<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateProject = (id: string, body: { name?: string; description?: string; settings?: Record<string, unknown> }) =>
  request<Project>(`/api/projects/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteProject = (id: string) =>
  request<void>(`/api/projects/${id}`, { method: "DELETE" });

// --- User Settings ---

export interface UserSettings {
  llm_provider: string;
  openai_api_key: string;
  azure_openai_api_key: string;
  azure_openai_endpoint: string;
  azure_openai_deployment: string;
  azure_openai_api_version: string;
}

export const getUserSettings = () =>
  request<UserSettings>("/api/settings");

export const updateUserSettings = (body: Partial<UserSettings>) =>
  request<UserSettings>("/api/settings", {
    method: "PATCH",
    body: JSON.stringify(body),
  });

// --- Permissions ---

export interface ProjectPermissions {
  role: "owner" | "admin" | "member";
  allowed_sections: string[];
  allowed_pages: string[] | null;
  write_pages: string[] | null;
  is_platform_admin: boolean;
}

export const getMyPermissions = () =>
  request<ProjectPermissions>("/api/me/permissions");

// --- Project Members ---

export interface ProjectMember {
  id: string;
  user_id: string | null;
  email: string;
  role: string;
  allowed_sections: string[];
  allowed_pages: string[] | null;
  write_pages: string[] | null;
  status: "active" | "pending";
  created_at: string;
}

export interface InviteResponse {
  id: string;
  email: string;
  role: string;
  allowed_sections: string[];
  allowed_pages: string[] | null;
  write_pages: string[] | null;
  status: "active" | "pending";
  invite_link: string | null;
  email_sent: boolean;
}

export const getProjectMembers = (projectId: string) =>
  request<{ data: ProjectMember[] }>(`/api/projects/${projectId}/members`);

export const inviteProjectMember = (
  projectId: string,
  body: {
    email: string;
    role?: string;
    allowed_sections?: string[];
    allowed_pages?: string[] | null;
    write_pages?: string[] | null;
  },
) =>
  request<InviteResponse>(`/api/projects/${projectId}/members`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateProjectMember = (
  projectId: string,
  memberId: string,
  body: {
    role?: string;
    allowed_sections?: string[];
    allowed_pages?: string[] | null;
    write_pages?: string[] | null;
  },
) =>
  request<ProjectMember>(`/api/projects/${projectId}/members/${memberId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const removeProjectMember = (projectId: string, memberId: string) =>
  request<void>(`/api/projects/${projectId}/members/${memberId}`, {
    method: "DELETE",
  });
