"use client";

import type { FeedbackOverview, OverviewBucket } from "@/lib/api";
import { BarSeriesChart } from "@/components/charts/bar-series-chart";
import { SectionShell } from "./section-shell";
import { SERIES, TIPS } from "./overview-constants";
import {
  formatBucketLabel,
  formatBucketTooltip,
  formatNumber,
  formatRate,
  spansMultipleYears,
} from "./overview-format";

export interface FeedbackSectionProps {
  feedback: FeedbackOverview | null;
  bucket: OverviewBucket;
  loading: boolean;
  error: unknown;
  refreshing: boolean;
  hovered: number | null;
  onHover: (i: number | null) => void;
}

export function FeedbackSection({
  feedback,
  bucket,
  loading,
  error,
  refreshing,
  hovered,
  onHover,
}: FeedbackSectionProps) {
  const points = feedback?.points ?? [];
  const multiYear = spansMultipleYears(points.map((p) => p.bucket));
  const totals = feedback?.totals;

  return (
    <SectionShell
      title="Feedback trend"
      tooltip={TIPS.feedbackRate}
      loading={loading}
      error={error}
      empty={!totals || totals.total === 0}
      emptyTitle="No feedback in this period"
      emptyHint="Thumbs from end users appear here once they arrive from your observability tool."
      emptyHref="/feedback"
      emptyCta="Go to Feedback"
      refreshing={refreshing}
    >
      <BarSeriesChart
        data={points}
        mode="stacked"
        rowKey={(p) => p.bucket}
        tooltipTitle={(p) => formatBucketTooltip(p.bucket, bucket)}
        xLabel={(p) => formatBucketLabel(p.bucket, bucket, { multiYear })}
        hovered={hovered}
        onHover={onHover}
        series={[
          { key: "positive", label: "Positive", className: SERIES.positive, value: (p) => p.positive },
          { key: "negative", label: "Negative", className: SERIES.negative, value: (p) => p.negative },
        ]}
        tooltipExtra={(p) =>
          p.total > 0 ? (
            <span className="text-slate-300">{formatRate(p.positive_rate)} positive</span>
          ) : null
        }
        footer={
          totals ? (
            <div className="flex flex-wrap gap-4 text-xs text-gray-500 dark:text-slate-400">
              <span>
                <span className="font-medium text-gray-700 dark:text-slate-200">
                  {formatNumber(totals.total)}
                </span>{" "}
                submissions
              </span>
              <span>
                <span className="font-medium text-gray-700 dark:text-slate-200">
                  {formatRate(totals.positive_rate)}
                </span>{" "}
                positive
              </span>
              <span>
                <span className="font-medium text-gray-700 dark:text-slate-200">
                  {formatNumber(totals.traces_with_feedback)}
                </span>{" "}
                traces with feedback
              </span>
            </div>
          ) : null
        }
      />
    </SectionShell>
  );
}
