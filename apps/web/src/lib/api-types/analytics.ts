/**
 * Types for the Analytics page — request-type clustering + retrieval insights.
 *
 * Generated from the backend OpenAPI schema — do not hand-edit shapes here.
 * Regenerate with `pnpm gen:api` after changing the Pydantic schemas.
 */

import type { components } from "./schema.gen";

type S = components["schemas"];

export type RequestOutcome = S["RequestOutcome"];
export type RequestClusterTheme = S["RequestClusterTheme"];
export type RequestClustersResponse = S["RequestClustersResponse"];
export type RetrievalSource = S["RetrievalSource"];
export type RetrievalActivityPoint = S["RetrievalActivityPoint"];
export type RetrievalActivityResponse = S["RetrievalActivityResponse"];
export type SpanNameCount = S["SpanNameCount"];
