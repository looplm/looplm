import type { OverviewBucket } from "@/lib/api";

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * Parse a YYYY-MM-DD bucket key at local midnight.
 *
 * `new Date("2026-08-10")` parses as UTC midnight and renders a day early anywhere west
 * of Greenwich. Appending the time forces local interpretation.
 */
export function parseBucketDate(key: string): Date {
  return new Date(`${key}T00:00:00`);
}

/**
 * ISO 8601 week number.
 *
 * Week 1 is the week containing the first Thursday of the year, so this shifts the date to
 * the Thursday of its own week and counts from Jan 4 (which is always in week 1). Dividing
 * the day-of-year by seven gets this wrong every few years.
 */
export function isoWeekNumber(date: Date): number {
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayOfWeek = (d.getDay() + 6) % 7; // Monday = 0
  d.setDate(d.getDate() - dayOfWeek + 3); // Thursday of this week
  const firstThursday = new Date(d.getFullYear(), 0, 4);
  const firstDayOfWeek = (firstThursday.getDay() + 6) % 7;
  firstThursday.setDate(firstThursday.getDate() - firstDayOfWeek + 3);
  return 1 + Math.round((d.getTime() - firstThursday.getTime()) / (7 * 86_400_000));
}

export function formatBucketLabel(
  key: string,
  bucket: OverviewBucket,
  opts: { multiYear?: boolean } = {},
): string {
  const d = parseBucketDate(key);
  if (bucket === "week") return `W${isoWeekNumber(d)}`;
  if (bucket === "month") {
    const month = MONTHS[d.getMonth()];
    return opts.multiYear ? `${month} ${String(d.getFullYear()).slice(2)}` : month;
  }
  return key.slice(5);
}

export function formatBucketTooltip(key: string, bucket: OverviewBucket): string {
  const d = parseBucketDate(key);
  if (bucket === "week") {
    const end = new Date(d);
    end.setDate(end.getDate() + 6);
    return `W${isoWeekNumber(d)}: ${shortDate(d)} to ${shortDate(end)}`;
  }
  if (bucket === "month") return `${fullMonth(d)} ${d.getFullYear()}`;
  return `${key} (${DAYS[d.getDay()]})`;
}

/** True when the bucket keys span more than one calendar year. */
export function spansMultipleYears(keys: string[]): boolean {
  if (keys.length < 2) return false;
  const first = parseBucketDate(keys[0]).getFullYear();
  const last = parseBucketDate(keys[keys.length - 1]).getFullYear();
  return first !== last;
}

function shortDate(d: Date): string {
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}

function fullMonth(d: Date): string {
  return [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ][d.getMonth()];
}

/** "Jul 27 to Aug 3", for the "vs previous period" tooltip. */
export function formatRangeLabel(startIso: string, endIso: string): string {
  const start = new Date(startIso);
  const end = new Date(endIso);
  return `${shortDate(start)} to ${shortDate(end)}`;
}

/** Whole days between two ISO timestamps, used to gate the bucket options. */
export function rangeInDays(start: string, end: string): number {
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms)) return 0;
  return Math.max(0, Math.round(ms / 86_400_000));
}

export function formatRate(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "n/a";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return Math.round(value).toLocaleString();
}

/** Format a KPI value according to its unit. */
export function formatKpiValue(
  value: number | null | undefined,
  unit: "rate" | "count",
): string {
  // "n/a" rather than a dash or a zero: a null KPI means "not configured", and a 0 would
  // claim the thing exists and is empty.
  if (value === null || value === undefined) return "n/a";
  return unit === "rate" ? formatRate(value) : formatNumber(value);
}
