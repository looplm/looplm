/**
 * Type definitions for LLM cost tracking.
 *
 * Generated from the backend OpenAPI schema — do not hand-edit shapes here.
 * Regenerate with `pnpm gen:api` after changing the Pydantic schemas.
 */

import type { components } from "./schema.gen";

type S = components["schemas"];

export type ServiceCostBreakdown = S["ServiceCostBreakdown"];
export type ModelCostBreakdown = S["ModelCostBreakdown"];
export type CostSummaryResponse = S["CostSummaryResponse"];
export type CostTrendPoint = S["CostTrendPoint"];
export type CostTrendResponse = S["CostTrendResponse"];
export type CostDetailItem = S["CostDetailItem"];
export type CostDetailsResponse = S["CostDetailsResponse"];
export type CostOverviewTrendPoint = S["CostOverviewTrendPoint"];
export type ModelCostItem = S["ModelCostItem"];
export type ServiceDetailItem = S["ServiceDetailItem"];
export type ServiceCostItem = S["ServiceCostItem"];
export type CostsOverviewResponse = S["CostsOverviewResponse"];
