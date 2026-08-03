/**
 * Type definitions for the user directory — named identities for raw end-user ids
 * and groups of them.
 *
 * Generated from the backend OpenAPI schema — do not hand-edit shapes here.
 * Regenerate with `pnpm gen:api` after changing the Pydantic schemas.
 * The CLIENT-SIDE section at the bottom has no backend schema and is hand-maintained.
 */

import type { components } from "./schema.gen";

type S = components["schemas"];

export type UserIdentity = S["UserIdentityResponse"];
export type UserIdentityListResponse = S["UserIdentityListResponse"];
export type CreateUserIdentityBody = S["UserIdentityCreate"];
export type UpdateUserIdentityBody = S["UserIdentityUpdate"];

export type UserGroup = S["UserGroupResponse"];
export type UserGroupListResponse = S["UserGroupListResponse"];
export type CreateUserGroupBody = S["UserGroupCreate"];
export type UpdateUserGroupBody = S["UserGroupUpdate"];

// --- Client-side only (no backend schema) ---

/** A raw user id seen in traces, as returned by `GET /api/traces/users`. */
export interface TraceUser {
  user_id: string;
  username: string | null;
  /** Traces carrying this id within the project. Absent on older API versions. */
  trace_count?: number;
}

/** How a raw user id should be labelled in the UI. */
export interface ResolvedUserName {
  /** Identity name, else the metadata username, else the raw id. */
  label: string;
  /** True when a stored identity supplied the name (drives mono vs prose styling). */
  mapped: boolean;
  /** The identity that owns this id, when there is one. */
  identityId?: string;
}

/** What the filter bar has selected; groups and identities expand to raw ids. */
export interface UserSelection {
  userIds: string[];
  identityIds: string[];
  groupIds: string[];
}
