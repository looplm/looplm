import type { OverviewBucket, SourceDimension } from "@/lib/api";

/**
 * Minimum range in days before a bucket size is worth offering.
 * A two-bar trend chart is noise, so week needs 3 weeks and month needs 3 months.
 */
export const BUCKET_MIN_DAYS: Record<OverviewBucket, number> = {
  day: 0,
  week: 21,
  month: 90,
};

/** Range the page offers to widen to when a bucket is picked below its minimum. */
export const BUCKET_WIDEN_DAYS: Record<OverviewBucket, number> = {
  day: 7,
  week: 30,
  month: 90,
};

export const BUCKET_LABELS: Record<OverviewBucket, string> = {
  day: "Day",
  week: "Week",
  month: "Month",
};

export const BUCKETS: OverviewBucket[] = ["day", "week", "month"];

/** Series colours, kept together so the whole page reads as one system. */
export const SERIES = {
  positive: "bg-green-500",
  negative: "bg-red-500",
  newUsers: "bg-indigo-500",
  returningUsers: "bg-violet-400",
  passRate: "text-emerald-500",
  covered: "bg-green-500",
  review: "bg-amber-500",
  missing: "bg-red-500",
  acked: "bg-slate-400",
  bar: "bg-indigo-500",
} as const;

export const SPARK = {
  feedback: "text-green-500",
  users: "text-indigo-500",
  passRate: "text-emerald-500",
  cumulative: "text-sky-500",
} as const;

/** The pass-rate goal drawn as a reference line on the eval chart. */
export const PASS_RATE_TARGET = 0.9;

export const SOURCE_DIMENSIONS: { key: SourceDimension; label: string; live: boolean }[] = [
  { key: "registry", label: "Source type", live: false },
  { key: "coverage", label: "Coverage", live: false },
  { key: "filetype", label: "File type", live: true },
  { key: "provider", label: "Providers", live: true },
];

/** Metric definitions surfaced through tooltips. These numbers are easy to misread. */
export const TIPS = {
  feedbackRate:
    "Share of end-user feedback submissions that were positive. Counted against the trace's own date, so it lines up with the usage numbers.",
  activeUsers: "Distinct users with at least one trace in the selected range.",
  newUsers:
    "Users whose first ever activity falls in this bucket. Someone who used the product before the selected range counts as returning, not new.",
  cumulative:
    "Total distinct users who have ever used the product, up to the end of each bucket. Includes users from before the selected range.",
  dau: "Distinct users active in the last 1, 7 and 30 days ending at the range end, not today. Independent of the bucket size.",
  stickiness:
    "Daily active users divided by monthly active users. Higher means people come back more often.",
  volumePerUser:
    "Traces with a known user divided by active users. Anonymous traffic is excluded from both, since it has no user to attribute.",
  passRate:
    "Pass rate of the most recent eval run with graded cases. Buckets with no run are gaps in the line, not zero.",
  passRateBucket:
    "Case-weighted per bucket, so a 5-case run and a 500-case run do not count equally.",
  evalProgress:
    "Distinct dataset cases with at least one successful eval result, out of all cases not marked needs work. Counted across all time, so narrowing the date range does not shrink it.",
  indexedSources:
    "Sources tracked in the registry for this project, meaning the documents that are expected to be retrievable.",
  coverage:
    "From the most recent gap analysis. Coverage is a snapshot, not a total, so runs are never added together.",
  fileType:
    "Read live from the index, so it may take a moment and is not filtered by the date range.",
} as const;
