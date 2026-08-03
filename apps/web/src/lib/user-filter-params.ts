/**
 * Turns the global user filter into query params.
 *
 * Every Observe endpoint takes the same `include_user_ids` / `exclude_user_ids` pair, but half of
 * them read a comma-separated string and half read repeated params — hence two helpers over one
 * source of truth. Group and identity selections are already expanded into raw ids by
 * `effectiveUserIds`, so the API never has to know about the directory.
 */

import type { GlobalFilters } from "@/components/global-filters-context";

type UserFilterSource = Pick<GlobalFilters, "userFilterMode" | "effectiveUserIds">;

function key(filters: UserFilterSource): "exclude_user_ids" | "include_user_ids" {
  return filters.userFilterMode === "exclude" ? "exclude_user_ids" : "include_user_ids";
}

/** Comma-separated form, for endpoints whose params are a `Record<string, string>`. */
export function userFilterParams(filters: UserFilterSource): Record<string, string> {
  if (filters.effectiveUserIds.length === 0) return {};
  return { [key(filters)]: filters.effectiveUserIds.join(",") };
}

/** Repeated-param form, for the typed clients that take string arrays. */
export function userFilterArrays(
  filters: UserFilterSource,
): { include_user_ids?: string[]; exclude_user_ids?: string[] } {
  if (filters.effectiveUserIds.length === 0) return {};
  return { [key(filters)]: filters.effectiveUserIds };
}
