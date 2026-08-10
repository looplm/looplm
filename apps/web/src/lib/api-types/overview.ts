/**
 * Overview page types.
 * Generated from the backend OpenAPI schema — do not hand-edit shapes here.
 * Regenerate with `pnpm gen:api`.
 */
import type { components } from "./schema.gen";

type S = components["schemas"];

export type OverviewPeriod = S["OverviewPeriod"];
// Pydantic inlines the bucket Literal rather than emitting a named schema, so derive it
// from the field to stay tied to the backend.
export type OverviewBucket = OverviewPeriod["bucket"];
export type OverviewDelta = S["Delta"];
export type OverviewKpi = S["OverviewKpi"];
export type OverviewSummary = S["OverviewSummaryResponse"];

export type FeedbackBucketPoint = S["FeedbackBucketPoint"];
export type FeedbackOverview = S["FeedbackOverview"];

export type AdoptionBucketPoint = S["AdoptionBucketPoint"];
export type AdoptionOverview = S["AdoptionOverview"];
export type AdoptionTotals = S["AdoptionTotals"];

export type EvalBucketPoint = S["EvalBucketPoint"];
export type EvalOverview = S["EvalOverview"];
export type EvalProgress = S["EvalProgress"];

export type SourcesOverview = S["SourcesOverviewResponse"];
export type RegistryDimension = S["RegistryDimension"];
export type RegistryDimensionValue = S["RegistryDimensionValue"];
export type CoverageBlock = S["CoverageBlock"];
export type CoveragePoint = S["CoveragePoint"];
export type OverviewProviderRef = S["ProviderRef"];
export type ProviderTypeAggregate = S["ProviderTypeAggregate"];

// --- Client-side only (no backend schema) ---

/** Which registry/index dimension the sources card is showing. */
export type SourceDimension = "registry" | "filetype" | "coverage" | "provider";

/** Per-provider state for the lazily-fetched live index reads. */
export interface LiveState<T> {
  status: "idle" | "loading" | "ok" | "error";
  data?: T;
  error?: unknown;
}

export interface OverviewSummaryParams {
  bucket: OverviewBucket;
  start_date?: string;
  end_date?: string;
  days?: number;
  environment?: string;
  include_user_ids?: string[];
  exclude_user_ids?: string[];
}
