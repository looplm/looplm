/**
 * Type definitions for the issues (signals → issues) feature.
 *
 * Generated from the backend OpenAPI schema — do not hand-edit shapes here.
 * Regenerate with `pnpm gen:api` after changing the Pydantic schemas.
 */

import type { components } from "./schema.gen";

type S = components["schemas"];

export type IssueStatus = S["IssueStatus"];
export type IssueListItem = S["IssueListItem"];
export type IssueEvidenceItem = S["EvidenceItem"];
export type IssueEventItem = S["EventItem"];
export type IssueDetail = S["IssueDetail"];
export type IssueDetectResponse = S["DetectResponse"];

// --- Client-side only (no backend schema) ---

/** Severity literal — surfaced inline on issue payloads, not a named API schema. */
export type IssueSeverity = "high" | "medium" | "low";
