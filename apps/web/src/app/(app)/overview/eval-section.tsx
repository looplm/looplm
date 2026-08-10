"use client";

import type { EvalOverview, OverviewBucket } from "@/lib/api";
import { LineChart } from "@/components/charts/line-chart";
import { MeterBar } from "@/components/charts/meter-bar";
import Tooltip from "@/components/tooltip";
import InfoIcon from "@/components/info-icon";
import { SectionShell } from "./section-shell";
import { PASS_RATE_TARGET, SERIES, TIPS } from "./overview-constants";
import {
  formatBucketLabel,
  formatBucketTooltip,
  formatNumber,
  formatRate,
  spansMultipleYears,
} from "./overview-format";

export interface EvalSectionProps {
  evals: EvalOverview | null;
  bucket: OverviewBucket;
  loading: boolean;
  error: unknown;
  refreshing: boolean;
  hovered: number | null;
  onHover: (i: number | null) => void;
}

export function EvalSection({
  evals,
  bucket,
  loading,
  error,
  refreshing,
  hovered,
  onHover,
}: EvalSectionProps) {
  const points = evals?.points ?? [];
  const multiYear = spansMultipleYears(points.map((p) => p.bucket));
  const progress = evals?.progress;

  return (
    <SectionShell
      title="Evaluation pass rate"
      tooltip={TIPS.passRateBucket}
      loading={loading}
      error={error}
      empty={!evals || evals.runs === 0}
      emptyTitle="No evaluation runs in this period"
      emptyHint="Trigger a run to start tracking pass rate over time."
      emptyHref="/evaluations"
      emptyCta="Go to Evaluations"
      refreshing={refreshing}
    >
      <LineChart
        data={points}
        rowKey={(p) => p.bucket}
        tooltipTitle={(p) => formatBucketTooltip(p.bucket, bucket)}
        xLabel={(p) => formatBucketLabel(p.bucket, bucket, { multiYear })}
        yDomain={[0, 1]}
        yFormat={(v) => `${Math.round(v * 100)}%`}
        target={{ value: PASS_RATE_TARGET, label: "Goal" }}
        hovered={hovered}
        onHover={onHover}
        series={[
          {
            key: "pass_rate",
            label: "Pass rate",
            className: SERIES.passRate,
            // null, not 0: a bucket with no run is a gap, not a failing suite.
            value: (p) => p.pass_rate ?? null,
            area: true,
          },
        ]}
      />
      {progress && progress.total > 0 ? (
        <div className="mt-4 pt-4 border-t border-gray-100 dark:border-slate-800">
          <div className="flex items-center justify-between text-xs mb-1.5">
            <span className="text-gray-500 dark:text-slate-400">
              Dataset coverage
              <Tooltip content={TIPS.evalProgress}>
                <span>
                  <InfoIcon />
                </span>
              </Tooltip>
            </span>
            <span className="font-medium text-gray-700 dark:text-slate-200 tabular-nums">
              {formatNumber(progress.evaluated)} of {formatNumber(progress.total)} cases
              evaluated
            </span>
          </div>
          <MeterBar
            total={progress.total}
            segments={[
              {
                key: "evaluated",
                label: "Evaluated",
                value: progress.evaluated,
                className: "bg-emerald-500",
              },
            ]}
          />
          <div className="flex flex-wrap gap-4 mt-2 text-xs text-gray-500 dark:text-slate-400">
            <span>
              Latest run{" "}
              <span className="font-medium text-gray-700 dark:text-slate-200">
                {formatRate(evals?.current_pass_rate)}
              </span>
            </span>
            <span>
              Window{" "}
              <span className="font-medium text-gray-700 dark:text-slate-200">
                {formatRate(evals?.window_pass_rate)}
              </span>
            </span>
            {evals && evals.runs_excluded_no_cases > 0 ? (
              <Tooltip content="Runs that finished with no graded cases, for example an aborted run. Excluded so they do not drag the curve down.">
                <span>
                  {evals.runs_excluded_no_cases} run
                  {evals.runs_excluded_no_cases === 1 ? "" : "s"} excluded
                  <InfoIcon />
                </span>
              </Tooltip>
            ) : null}
          </div>
        </div>
      ) : null}
    </SectionShell>
  );
}
