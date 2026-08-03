/**
 * API functions for the user directory — naming raw end-user ids and grouping them.
 *
 * Reads go through `cachedRequest` because the directory is fetched on every page load to
 * resolve display names; mutations invalidate that cache so renames show up immediately.
 */

import type {
  CreateUserGroupBody,
  CreateUserIdentityBody,
  UpdateUserGroupBody,
  UpdateUserIdentityBody,
  UserGroup,
  UserGroupListResponse,
  UserIdentity,
  UserIdentityListResponse,
} from "../api-types";
import { cachedRequest, invalidateCache, request } from "./client";

const IDENTITIES = "/api/user-identities";
const GROUPS = "/api/user-groups";

function invalidateDirectory(): void {
  invalidateCache(IDENTITIES);
  invalidateCache(GROUPS);
}

// --- Identities ---

export const getUserIdentities = () =>
  cachedRequest<UserIdentityListResponse>(IDENTITIES);

export const createUserIdentity = async (body: CreateUserIdentityBody) => {
  const created = await request<UserIdentity>(IDENTITIES, { method: "POST", body: JSON.stringify(body) });
  invalidateDirectory();
  return created;
};

export const updateUserIdentity = async (id: string, body: UpdateUserIdentityBody) => {
  const updated = await request<UserIdentity>(`${IDENTITIES}/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  invalidateDirectory();
  return updated;
};

export const deleteUserIdentity = async (id: string) => {
  await request<void>(`${IDENTITIES}/${id}`, { method: "DELETE" });
  invalidateDirectory();
};

// --- Groups ---

export const getUserGroups = () => cachedRequest<UserGroupListResponse>(GROUPS);

export const createUserGroup = async (body: CreateUserGroupBody) => {
  const created = await request<UserGroup>(GROUPS, { method: "POST", body: JSON.stringify(body) });
  invalidateDirectory();
  return created;
};

export const updateUserGroup = async (id: string, body: UpdateUserGroupBody) => {
  const updated = await request<UserGroup>(`${GROUPS}/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  invalidateDirectory();
  return updated;
};

export const deleteUserGroup = async (id: string) => {
  await request<void>(`${GROUPS}/${id}`, { method: "DELETE" });
  invalidateDirectory();
};
