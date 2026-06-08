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

/**
 * Test-balance: is a value's share of test cases proportional to its share of
 * the indexed content? Target-free — compares each value's "test attention"
 * against its fair share by chunk volume (≈ token share, à la Ragas). When the
 * category has no tests yet, or a slice is too small to proportionally warrant
 * even one test, there's no signal (the "% of index" magnitude carries it).
 */
export type BalanceStatus = "untested" | "under" | "light" | "balanced" | "none";

export interface TestBalance {
  status: BalanceStatus;
  expected: number; // fair share of test cases by content volume
}

export function testBalance(args: {
  indexedCount: number;
  coveringCases: number;
  totalDocs: number;
  totalCases: number;
}): TestBalance {
  const { indexedCount, coveringCases, totalDocs, totalCases } = args;
  if (totalCases <= 0 || totalDocs <= 0) return { status: "none", expected: 0 };
  const expected = (indexedCount / totalDocs) * totalCases;
  if (expected < 1) return { status: "none", expected };
  let status: BalanceStatus;
  if (coveringCases === 0) status = "untested";
  else if (coveringCases < 0.5 * expected) status = "under";
  else if (coveringCases < expected) status = "light";
  else status = "balanced";
  return { status, expected };
}

export const BALANCE_LABEL: Record<BalanceStatus, string> = {
  untested: "Untested",
  under: "Under-tested",
  light: "Light",
  balanced: "Balanced",
  none: "",
};

export const BALANCE_PILL: Record<BalanceStatus, string> = {
  untested: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400",
  under: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400",
  light: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400",
  balanced: "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400",
  none: "",
};
