"use client";

import type { OverviewKpi, OverviewPeriod } from "@/lib/api";
import Tooltip from "@/components/tooltip";
import InfoIcon from "@/components/info-icon";
import { Sparkline } from "@/components/charts/sparkline";
import { SPARK, TIPS } from "./overview-constants";
import { formatKpiValue, formatRangeLabel } from "./overview-format";

const SPARK_COLOR: Record<string, string> = {
  feedback_rate: SPARK.feedback,
  active_users: SPARK.users,
  eval_pass_rate: SPARK.passRate,
  indexed_sources: SPARK.cumulative,
};

const KPI_TIP: Record<string, string> = {
  feedback_rate: TIPS.feedbackRate,
  active_users: TIPS.activeUsers,
  eval_pass_rate: TIPS.passRate,
  indexed_sources: TIPS.indexedSources,
};

interface DeltaChipProps {
  changePct: number | null | undefined;
  higherIsBetter: boolean;
  rangeTooltip: string;
}

/**
 * The "vs previous period" arrow.
 *
 * A null change renders nothing at all. The backend returns null when the previous window
 * has no usable baseline, and showing a 0% or +100% there would be a fabricated number.
 */
function DeltaChip({ changePct, higherIsBetter, rangeTooltip }: DeltaChipProps) {
  if (changePct === null || changePct === undefined) {
    return (
      <Tooltip content="No comparable previous period">
        <span className="text-xs text-gray-400 dark:text-slate-500">no baseline</span>
      </Tooltip>
    );
  }
  if (Math.abs(changePct) < 0.01) {
    return (
      <Tooltip content={rangeTooltip}>
        <span className="text-xs text-gray-400 dark:text-slate-500">flat</span>
      </Tooltip>
    );
  }
  const rising = changePct > 0;
  // Colour by whether the movement is good, never by its sign alone: a lower-is-better
  // metric added later would otherwise be silently mis-coloured.
  const good = rising === higherIsBetter;
  const color = good
    ? "text-green-600 dark:text-green-400"
    : "text-red-600 dark:text-red-400";
  return (
    <Tooltip content={rangeTooltip}>
      <span className={`text-xs font-medium ${color}`}>
        {rising ? "▲" : "▼"} {(Math.abs(changePct) * 100).toFixed(0)}% vs prev
      </span>
    </Tooltip>
  );
}

export interface OverviewKpiRowProps {
  kpis: OverviewKpi[];
  period: OverviewPeriod;
}

export function OverviewKpiRow({ kpis, period }: OverviewKpiRowProps) {
  const rangeTooltip = `${formatRangeLabel(period.start, period.end)} vs ${formatRangeLabel(
    period.previous_start,
    period.previous_end,
  )}`;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {kpis.map((kpi) => {
        const series = (kpi.series ?? []).filter((v): v is number => v !== null);
        return (
          <div
            key={kpi.key}
            className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4"
          >
            <div className="text-xs text-gray-500 dark:text-slate-400">
              {kpi.label}
              {KPI_TIP[kpi.key] ? (
                <Tooltip content={KPI_TIP[kpi.key]}>
                  <span>
                    <InfoIcon />
                  </span>
                </Tooltip>
              ) : null}
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-3xl font-semibold text-gray-900 dark:text-slate-100 tabular-nums">
                {formatKpiValue(kpi.value, kpi.unit)}
              </span>
              <DeltaChip
                changePct={kpi.change_pct}
                higherIsBetter={kpi.higher_is_better}
                rangeTooltip={rangeTooltip}
              />
            </div>
            {kpi.sub ? (
              <div className="mt-1 text-xs text-gray-500 dark:text-slate-400">{kpi.sub}</div>
            ) : null}
            {series.length > 1 ? (
              <div className="mt-2">
                <Sparkline data={series} className={SPARK_COLOR[kpi.key] ?? SPARK.users} />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
