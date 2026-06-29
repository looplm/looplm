/**
 * Shared constants, helpers, and types for the wanted-sources registry UI.
 */

import type { GapRowStatus, SourceExpectation } from "@/lib/api-types/source-registry";

export const STATUS_CHIP: Record<string, { label: string; cls: string }> = {
  covered_url: {
    label: "Covered (URL)",
    cls: "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400",
  },
  covered_title: {
    label: "Covered (title)",
    cls: "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400",
  },
  review: {
    label: "Review",
    cls: "bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400",
  },
  missing: {
    label: "Missing",
    cls: "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400",
  },
  acked: {
    label: "Acknowledged",
    cls: "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400",
  },
};

// Status filter buckets. The two "covered" verdicts collapse into one bucket.
export type FilterBucket = "covered" | "review" | "missing" | "acked";
export const ALL_BUCKETS: FilterBucket[] = ["covered", "review", "missing", "acked"];
export const DEFAULT_BUCKETS: FilterBucket[] = ["review", "missing"];

export const BUCKET_LABEL: Record<FilterBucket, string> = {
  covered: "covered",
  review: "to review",
  missing: "missing",
  acked: "acknowledged",
};
export const BUCKET_CHIP: Record<FilterBucket, string> = {
  covered: STATUS_CHIP.covered_url.cls,
  review: STATUS_CHIP.review.cls,
  missing: STATUS_CHIP.missing.cls,
  acked: STATUS_CHIP.acked.cls,
};

export function bucketOf(status: GapRowStatus | null): FilterBucket | null {
  if (!status) return null;
  if (status === "covered_url" || status === "covered_title") return "covered";
  return status;
}

// Dimensions a user can cluster the registry by, in default-preference order.
export const GROUP_DIMENSIONS: { key: keyof SourceExpectation; label: string }[] = [
  { key: "sparte", label: "Sparte" },
  { key: "hierarchie", label: "Hierarchie" },
  { key: "typ", label: "Type" },
  { key: "publisher", label: "Publisher" },
  { key: "thema", label: "Thema" },
  { key: "adapter_tag", label: "Adapter" },
];

// Sort order within a group: actionable rows first.
export const STATUS_ORDER: Record<string, number> = {
  missing: 0,
  review: 1,
  covered_url: 2,
  covered_title: 2,
  acked: 3,
};

export type Group = {
  key: string;
  label: string;
  items: SourceExpectation[];
  counts: Record<FilterBucket, number>;
};

/** Compact a URL to `host/…/last-segment` for side-by-side comparison. */
export function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, "");
    const segments = u.pathname.split("/").filter(Boolean);
    const last = segments[segments.length - 1];
    if (!last) return host;
    return segments.length > 1 ? `${host}/…/${last}` : `${host}/${last}`;
  } catch {
    return url;
  }
}

/** Decode an uploaded CSV: try UTF-8 first, fall back to cp1252 exports. */
export async function readCsvFile(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const utf8 = new TextDecoder("utf-8", { fatal: false }).decode(buffer);
  if (!utf8.includes("�")) return utf8;
  return new TextDecoder("windows-1252").decode(buffer);
}
