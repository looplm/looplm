"use client";

import type { OverviewBucket } from "@/lib/api";
import { BUCKETS, BUCKET_LABELS, BUCKET_MIN_DAYS, BUCKET_WIDEN_DAYS } from "./overview-constants";

export interface BucketToggleProps {
  value: OverviewBucket;
  onChange: (bucket: OverviewBucket) => void;
  /** Days in the currently selected global range; gates the larger buckets. */
  rangeDays: number;
  /** Switch bucket and widen the shared range in one gesture. */
  onWiden: (bucket: OverviewBucket) => void;
}

/**
 * Day / week / month pills, styled as a sibling of the global filter bar's range pills.
 *
 * A bucket below its minimum range is shown muted rather than hidden: hiding it leaves the
 * user guessing why monthly is missing, while a muted pill that widens the range on click
 * explains itself and fixes itself.
 */
export function BucketToggle({ value, onChange, rangeDays, onWiden }: BucketToggleProps) {
  const pillClass = (active: boolean, enabled: boolean) =>
    `px-3 py-1 text-xs font-medium rounded-full transition-all ${
      active
        ? "bg-indigo-600 text-white shadow-sm"
        : enabled
          ? "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 hover:bg-gray-200 dark:hover:bg-slate-700 hover:text-gray-700 dark:hover:text-slate-200"
          : "bg-gray-50 dark:bg-slate-800/50 text-gray-300 dark:text-slate-600 hover:text-gray-500 dark:hover:text-slate-400"
    }`;

  return (
    <div className="flex items-center gap-1">
      <span className="text-xs text-gray-500 dark:text-slate-400 mr-1">Bucket</span>
      {BUCKETS.map((bucket) => {
        const minDays = BUCKET_MIN_DAYS[bucket];
        const enabled = rangeDays >= minDays;
        const widenTo = BUCKET_WIDEN_DAYS[bucket];
        return (
          <button
            key={bucket}
            type="button"
            onClick={() => (enabled ? onChange(bucket) : onWiden(bucket))}
            className={pillClass(value === bucket, enabled)}
            title={
              enabled
                ? `Group by ${bucket}`
                : `Grouping by ${bucket} needs at least ${minDays} days. Click to widen the range to ${widenTo} days.`
            }
          >
            {BUCKET_LABELS[bucket]}
          </button>
        );
      })}
    </div>
  );
}
