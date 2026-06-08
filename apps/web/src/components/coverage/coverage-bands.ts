/**
 * Shared low/medium/high banding for chunk-coverage % (volume-weighted —
 * "share of the total index chunks that sit in covered values").
 *
 * Thresholds in one place so they're easy to tune:
 *   Low    < 50%   — most indexed content has no eval coverage
 *   Medium 50–79%
 *   High   ≥ 80%   — the bulk of the index is covered
 */

export type CoverageBand = "low" | "medium" | "high" | "none";

export const HIGH_IMPACT_SHARE = 10; // an uncovered value ≥ this % of the index is a big hole

export function chunkCoverageBand(pct?: number | null): CoverageBand {
  if (pct == null) return "none";
  if (pct < 50) return "low";
  if (pct < 80) return "medium";
  return "high";
}

export const BAND_LABEL: Record<CoverageBand, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  none: "—",
};

export const BAND_PILL: Record<CoverageBand, string> = {
  low: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400",
  medium: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400",
  high: "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400",
  none: "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400",
};

export const BAND_ACCENT: Record<CoverageBand, "red" | "amber" | "green" | undefined> = {
  low: "red",
  medium: "amber",
  high: "green",
  none: undefined,
};
