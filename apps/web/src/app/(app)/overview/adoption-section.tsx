"use client";

import type { AdoptionOverview, OverviewBucket } from "@/lib/api";
import { BarSeriesChart } from "@/components/charts/bar-series-chart";
import { Sparkline } from "@/components/charts/sparkline";
import { MeterBar } from "@/components/charts/meter-bar";
import Tooltip from "@/components/tooltip";
import InfoIcon from "@/components/info-icon";
import { SectionShell } from "./section-shell";
import { SERIES, SPARK, TIPS } from "./overview-constants";
import {
  formatBucketLabel,
  formatBucketTooltip,
  formatNumber,
  formatRate,
  spansMultipleYears,
} from "./overview-format";

export interface AdoptionSectionProps {
  adoption: AdoptionOverview | null;
  bucket: OverviewBucket;
  loading: boolean;
  error: unknown;
  refreshing: boolean;
  hovered: number | null;
  onHover: (i: number | null) => void;
}

function Metric({
  label,
  value,
  tooltip,
  meter,
}: {
  label: string;
  value: string;
  tooltip: string;
  meter?: { value: number; total: number };
}) {
  return (
    <div>
      <div className="text-xs text-gray-500 dark:text-slate-400">
        {label}
        <Tooltip content={tooltip}>
          <span>
            <InfoIcon />
          </span>
        </Tooltip>
      </div>
      <div className="text-2xl font-semibold text-gray-900 dark:text-slate-100 tabular-nums">
        {value}
      </div>
      {meter ? (
        <MeterBar
          className="mt-1"
          height="h-1.5"
          total={meter.total}
          segments={[
            { key: "v", label: label, value: meter.value, className: SERIES.newUsers },
          ]}
        />
      ) : null}
    </div>
  );
}

export function AdoptionSection({
  adoption,
  bucket,
  loading,
  error,
  refreshing,
  hovered,
  onHover,
}: AdoptionSectionProps) {
  const points = adoption?.points ?? [];
  const totals = adoption?.totals;
  const multiYear = spansMultipleYears(points.map((p) => p.bucket));
  const cumulative = points.map((p) => p.cumulative_users);

  return (
    <SectionShell
      title="User adoption"
      tooltip={TIPS.newUsers}
      action={
        cumulative.length > 1 ? (
          <div className="flex items-center gap-2 w-32">
            <Sparkline data={cumulative} className={SPARK.cumulative} />
            <Tooltip content={TIPS.cumulative}>
              <span className="text-xs font-medium text-gray-700 dark:text-slate-200 tabular-nums">
                {formatNumber(totals?.cumulative_users)}
              </span>
            </Tooltip>
          </div>
        ) : null
      }
      loading={loading}
      error={error}
      empty={!totals || totals.traces === 0}
      emptyTitle="No user activity in this period"
      emptyHint="Traces synced from your observability tool populate this chart."
      emptyHref="/traces"
      emptyCta="Go to Traces"
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
          { key: "new", label: "New", className: SERIES.newUsers, value: (p) => p.new_users },
          {
            key: "returning",
            label: "Returning",
            className: SERIES.returningUsers,
            value: (p) => p.returning_users,
          },
        ]}
        tooltipExtra={(p) => (
          <span className="text-slate-300">{formatNumber(p.traces)} traces</span>
        )}
      />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-4 pt-4 border-t border-gray-100 dark:border-slate-800">
        <Metric
          label="Daily active"
          value={formatNumber(totals?.dau)}
          tooltip={TIPS.dau}
        />
        <Metric
          label="Weekly active"
          value={formatNumber(totals?.wau)}
          tooltip={TIPS.dau}
        />
        <Metric
          label="Monthly active"
          value={formatNumber(totals?.mau)}
          tooltip={TIPS.dau}
        />
        <Metric
          label="Stickiness"
          value={formatRate(totals?.stickiness)}
          tooltip={TIPS.stickiness}
          meter={
            totals?.stickiness !== null && totals?.stickiness !== undefined
              ? { value: totals.stickiness, total: 1 }
              : undefined
          }
        />
      </div>
      <div className="mt-3 text-xs text-gray-500 dark:text-slate-400">
        <Tooltip content={TIPS.volumePerUser}>
          <span>
            <span className="font-medium text-gray-700 dark:text-slate-200 tabular-nums">
              {totals?.avg_traces_per_active_user?.toFixed(1) ?? "n/a"}
            </span>{" "}
            traces per active user
            <InfoIcon />
          </span>
        </Tooltip>
      </div>
    </SectionShell>
  );
}
