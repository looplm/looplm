"use client";

import { useEffect, useMemo, useState } from "react";
import { getDashboardStats, type DashboardStats } from "@/lib/api";
import { useGlobalFilters } from "@/components/global-filters-context";
import Tooltip from "@/components/tooltip";
import { UsageTrendChart } from "./usage-trend-chart";
import { Sparkline } from "./sparkline";

function InfoIcon() {
  return (
    <svg className="inline-block w-3.5 h-3.5 ml-1 text-gray-400 dark:text-slate-500" viewBox="0 0 16 16" fill="currentColor">
      <path fillRule="evenodd" d="M8 15A7 7 0 108 1a7 7 0 000 14zm.75-10.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zM7.25 8a.75.75 0 011.5 0v3a.75.75 0 01-1.5 0V8z" clipRule="evenodd" />
    </svg>
  );
}

type SortKey =
  | "date"
  | "total"
  | "unique_users"
  | "unique_threads"
  | "feedback_positive"
  | "feedback_negative"
  | "pos_rate"
  | "fb_rate";
type SortDir = "asc" | "desc";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const { startDate, endDate, environment, userFilterMode, filteredUsers, traceNames } = useGlobalFilters();

  useEffect(() => {
    setStats(null);
    setError(null);
    const params: { days?: number; start_date?: string; end_date?: string; environment?: string; include_user_ids?: string[]; exclude_user_ids?: string[] } = {};
    if (startDate) params.start_date = new Date(startDate).toISOString();
    if (endDate) params.end_date = new Date(endDate).toISOString();
    if (!startDate) params.days = 7;
    if (environment && environment !== "all") params.environment = environment;
    if (filteredUsers.length > 0) {
      if (userFilterMode === "exclude") params.exclude_user_ids = filteredUsers;
      else params.include_user_ids = filteredUsers;
    }
    getDashboardStats(params).then(setStats).catch((e) => setError(e.message));
  }, [startDate, endDate, environment, userFilterMode, filteredUsers, traceNames]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sortedTrends = useMemo(() => {
    if (!stats) return [];
    const sorted = [...stats.trends].sort((a, b) => {
      let aVal: number | string;
      let bVal: number | string;
      if (sortKey === "pos_rate") {
        const aTotal = a.feedback_positive + a.feedback_negative;
        const bTotal = b.feedback_positive + b.feedback_negative;
        aVal = aTotal > 0 ? a.feedback_positive / aTotal : 0;
        bVal = bTotal > 0 ? b.feedback_positive / bTotal : 0;
      } else if (sortKey === "fb_rate") {
        aVal = a.total > 0 ? a.traces_with_feedback / a.total : 0;
        bVal = b.total > 0 ? b.traces_with_feedback / b.total : 0;
      } else {
        aVal = a[sortKey];
        bVal = b[sortKey];
      }
      if (aVal < bVal) return -1;
      if (aVal > bVal) return 1;
      return 0;
    });
    return sortDir === "desc" ? sorted.reverse() : sorted;
  }, [stats, sortKey, sortDir]);

  if (error) {
    return (
      <div>
        <h1 className="text-3xl font-bold mb-8">Dashboard</h1>
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-8 text-center text-gray-500 dark:text-slate-400">
          <p>Unable to load dashboard data.</p>
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-2">{error}</p>
        </div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div>
        <h1 className="text-3xl font-bold mb-8">Dashboard</h1>
        <p className="text-gray-500 dark:text-slate-400">Loading...</p>
      </div>
    );
  }

  const { totals, feedback, latency, threads } = stats;
  const fmtMs = (ms: number | null | undefined) =>
    ms == null ? "N/A" : ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
  // Regression values arrive in the metric's native unit: latency in ms, rates in 0–1.
  const fmtRegression = (metric: string, v: number) =>
    metric === "latency_p95" ? fmtMs(Math.round(v)) : `${(v * 100).toFixed(1)}%`;

  // "Previous period" = the equally-long window immediately before the selected one.
  const periodStart = new Date(stats.period.start);
  const prevWindowMs = new Date(stats.period.end).getTime() - periodStart.getTime();
  const prevStart = new Date(periodStart.getTime() - prevWindowMs);
  const fmtDay = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const prevRangeLabel = `${fmtDay(prevStart)} – ${fmtDay(periodStart)}`;

  // Chronological daily series for the KPI sparklines.
  const chrono = [...stats.trends].sort((a, b) => a.date.localeCompare(b.date));

  return (
    <div>
      <h1 className="text-3xl font-bold mb-8">Dashboard</h1>

      {/* Regression banner: metrics that worsened vs the previous window */}
      {stats.regressions.length > 0 && (
        <div className="mb-8 rounded-xl border border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-500/10 p-4">
          <p className="text-sm font-semibold text-amber-800 dark:text-amber-300 mb-2">
            ⚠️ Regression vs previous period
            <span className="font-normal text-amber-700 dark:text-amber-400/90"> ({prevRangeLabel})</span>
            <Tooltip content={`Compared against the equally-long window immediately before the selected period, here ${prevRangeLabel}. A metric is flagged when it got materially worse.`}>
              <InfoIcon />
            </Tooltip>
          </p>
          <div className="flex flex-wrap gap-x-6 gap-y-1">
            {stats.regressions.map((r) => (
              <span key={r.metric} className="text-sm text-amber-800 dark:text-amber-200">
                {r.label}: <span className="font-semibold">+{(r.change_pct * 100).toFixed(0)}%</span>
                <span className="text-amber-600 dark:text-amber-400/80">
                  {" "}({fmtRegression(r.metric, r.previous)} → {fmtRegression(r.metric, r.current)})
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        {[
          { label: "Total Traces", value: totals.traces.toLocaleString(), tooltip: "Total number of traces in the selected period", series: chrono.map((d) => d.total), spark: "text-indigo-500" },
          { label: "Unique Users", value: totals.unique_users.toLocaleString(), tooltip: "Number of distinct users who generated traces", series: chrono.map((d) => d.unique_users), spark: "text-violet-400" },
          { label: "Unique Threads", value: totals.unique_threads.toLocaleString(), tooltip: "Number of distinct conversation threads", series: chrono.map((d) => d.unique_threads), spark: "text-sky-400" },
          {
            label: "Feedback Rate",
            value: totals.traces > 0
              ? `${((feedback.traces_with_feedback / totals.traces) * 100).toFixed(1)}%`
              : "0.0%",
            color: "text-green-500",
            tooltip: "Share of traces that received at least one feedback submission (traces with feedback ÷ total traces).",
            series: chrono.map((d) => (d.total > 0 ? (d.traces_with_feedback / d.total) * 100 : 0)),
            spark: "text-green-500",
          },
        ].map((s) => (
          <div key={s.label} className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
            <p className="text-sm text-gray-500 dark:text-slate-400 mb-1">
              {s.label}
              {s.tooltip && (
                <Tooltip content={s.tooltip}><InfoIcon /></Tooltip>
              )}
            </p>
            <p className={`text-3xl font-bold ${s.color || ""}`}>{s.value}</p>
            <div className="mt-3 h-7">
              <Sparkline data={s.series} className={s.spark} />
            </div>
          </div>
        ))}
      </div>

      {/* Latency distribution + conversation metrics */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6">
          <h2 className="text-lg font-semibold mb-4">
            Latency
            <Tooltip content="How long traces take, shown as percentiles. Sort every trace from fastest to slowest: a percentile is the speed you're at or below for that share of traces. P50 is the typical case. P95 and P99 are the slow tail, the problems an average would hide.">
              <InfoIcon />
            </Tooltip>
          </h2>
          <div className="space-y-3">
            {(() => {
              const latMax = Math.max(latency.p50_ms ?? 0, latency.p95_ms ?? 0, latency.p99_ms ?? 0, 1);
              return [
                { label: "p50", ms: latency.p50_ms, bar: "bg-indigo-300 dark:bg-indigo-400/70", tooltip: "Median: half of traces are faster than this, half slower. The typical experience." },
                { label: "p95", ms: latency.p95_ms, bar: "bg-indigo-400 dark:bg-indigo-400", tooltip: "95% of traces are faster than this; only the slowest 5% are worse." },
                { label: "p99", ms: latency.p99_ms, bar: "bg-indigo-600 dark:bg-indigo-500", tooltip: "99% of traces are faster than this; only the worst 1% are slower. The tail, your unluckiest users." },
              ].map((s) => (
                <div key={s.label} className="flex items-center gap-3">
                  <span className="text-xs text-gray-500 dark:text-slate-400 uppercase tracking-wide w-9 shrink-0">
                    {s.label}
                    <Tooltip content={s.tooltip}><InfoIcon /></Tooltip>
                  </span>
                  <div className="flex-1 h-2.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
                    <div className={`h-full rounded-full ${s.bar}`} style={{ width: `${((s.ms ?? 0) / latMax) * 100}%` }} />
                  </div>
                  <span className="text-sm font-bold tabular-nums w-16 text-right shrink-0">{fmtMs(s.ms)}</span>
                </div>
              ));
            })()}
          </div>
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-3">
            Across {latency.count.toLocaleString()} traces with a recorded duration.
          </p>
        </div>

        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6">
          <h2 className="text-lg font-semibold mb-4">
            Conversations
            <Tooltip content="Signals derived from grouping traces into threads: multi-turn share and length.">
              <InfoIcon />
            </Tooltip>
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {[
              { label: "Multi-turn", value: `${(threads.multi_turn_rate * 100).toFixed(0)}%`, bar: threads.multi_turn_rate, barColor: "bg-indigo-500", tooltip: "Share of threads with more than one trace" },
              { label: "Avg length", value: threads.avg_thread_length.toFixed(1), tooltip: "Average traces per thread" },
              { label: "p95 length", value: String(threads.p95_thread_length), tooltip: "95% of threads are this many traces long or shorter; only the longest 5% have more." },
            ].map((s) => (
              <div key={s.label}>
                <p className="text-xs text-gray-500 dark:text-slate-400">
                  {s.label}
                  {s.tooltip && <Tooltip content={s.tooltip}><InfoIcon /></Tooltip>}
                </p>
                <p className={`text-2xl font-bold ${s.color || ""}`}>{s.value}</p>
                {s.bar !== undefined && (
                  <div className="mt-2 h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
                    <div className={`h-full rounded-full ${s.barColor}`} style={{ width: `${Math.min(s.bar, 1) * 100}%` }} />
                  </div>
                )}
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-400 dark:text-slate-500 mt-3">
            Across {threads.total_threads.toLocaleString()} threads.
          </p>
        </div>
      </div>

      {/* Feedback Summary */}
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 mb-8">
        <h2 className="text-lg font-semibold mb-4">Feedback Summary</h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-10 gap-y-6">
          {/* Coverage: share of traces that got any feedback. */}
          <div>
            <div className="flex items-baseline justify-between mb-2">
              <span className="text-xs font-medium text-gray-500 dark:text-slate-400">
                Coverage
                <Tooltip content="Share of traces that received at least one feedback submission."><InfoIcon /></Tooltip>
              </span>
              <span className="text-xs text-gray-500 dark:text-slate-400">
                <span className="font-semibold text-gray-900 dark:text-slate-100">{feedback.traces_with_feedback.toLocaleString()}</span>
                {" of "}{totals.traces.toLocaleString()} traces
                {" ("}{totals.traces > 0 ? ((feedback.traces_with_feedback / totals.traces) * 100).toFixed(1) : "0.0"}%)
              </span>
            </div>
            <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-slate-800">
              <div
                className="bg-green-500"
                style={{ width: `${totals.traces > 0 ? (feedback.traces_with_feedback / totals.traces) * 100 : 0}%` }}
              />
            </div>
            <div className="flex gap-4 mt-2 text-xs text-gray-500 dark:text-slate-400">
              <span><span className="inline-block w-2 h-2 rounded-full bg-green-500 mr-1.5 align-middle" />With feedback {feedback.traces_with_feedback.toLocaleString()} <span className="text-gray-400 dark:text-slate-500">({totals.traces > 0 ? Math.round((feedback.traces_with_feedback / totals.traces) * 100) : 0}%)</span></span>
              <span><span className="inline-block w-2 h-2 rounded-full bg-gray-200 dark:bg-slate-700 mr-1.5 align-middle" />No feedback {feedback.no_feedback_traces.toLocaleString()} <span className="text-gray-400 dark:text-slate-500">({totals.traces > 0 ? Math.round((feedback.no_feedback_traces / totals.traces) * 100) : 0}%)</span></span>
            </div>
          </div>

          {/* Sentiment: positive vs negative across feedback submissions. */}
          <div>
            <div className="flex items-baseline justify-between mb-2">
              <span className="text-xs font-medium text-gray-500 dark:text-slate-400">
                Sentiment
                <Tooltip content="Positive vs negative across all feedback submissions. A trace can receive several, so this counts submissions, not traces."><InfoIcon /></Tooltip>
              </span>
              <span className="text-xs text-gray-500 dark:text-slate-400">
                <span className="font-semibold text-gray-900 dark:text-slate-100">{feedback.total.toLocaleString()}</span> submissions
              </span>
            </div>
            <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-slate-800">
              <div className="bg-green-500" style={{ width: `${feedback.total > 0 ? (feedback.positive / feedback.total) * 100 : 0}%` }} />
              <div className="bg-red-400" style={{ width: `${feedback.total > 0 ? (feedback.negative / feedback.total) * 100 : 0}%` }} />
            </div>
            <div className="flex gap-4 mt-2 text-xs text-gray-500 dark:text-slate-400">
              <span><span className="inline-block w-2 h-2 rounded-full bg-green-500 mr-1.5 align-middle" />Positive {feedback.positive.toLocaleString()} <span className="text-gray-400 dark:text-slate-500">({feedback.total > 0 ? Math.round((feedback.positive / feedback.total) * 100) : 0}%)</span></span>
              <span><span className="inline-block w-2 h-2 rounded-full bg-red-400 mr-1.5 align-middle" />Negative {feedback.negative.toLocaleString()} <span className="text-gray-400 dark:text-slate-500">({feedback.total > 0 ? Math.round((feedback.negative / feedback.total) * 100) : 0}%)</span></span>
            </div>
          </div>
        </div>
      </div>

      {/* Usage trends chart */}
      <UsageTrendChart data={[...stats.trends].sort((a, b) => a.date.localeCompare(b.date))} />

      {/* Usage trends table */}
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 mb-8">
        <h2 className="text-lg font-semibold mb-4">Usage Trends</h2>
        {sortedTrends.length === 0 ? (
          <p className="text-gray-500 dark:text-slate-400 text-sm">No trend data available.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-400">
                  {([
                    { key: "date" as SortKey, label: "Date", align: "text-left" },
                    { key: "total" as SortKey, label: "Traces", align: "text-right" },
                    { key: "unique_users" as SortKey, label: "Users", align: "text-right" },
                    { key: "unique_threads" as SortKey, label: "Threads", align: "text-right" },
                    { key: "feedback_positive" as SortKey, label: "Positive", align: "text-right", tooltip: "Number of positive feedback scores" },
                    { key: "feedback_negative" as SortKey, label: "Negative", align: "text-right", tooltip: "Number of negative feedback scores" },
                    { key: "fb_rate" as SortKey, label: "Fb Rate", align: "text-right", tooltip: "Percentage of traces that received at least one feedback score" },
                    { key: "pos_rate" as SortKey, label: "Pos Rate", align: "text-right", tooltip: "Percentage of feedback scores that were positive" },
                  ] as const).map((col) => (
                    <th
                      key={col.key}
                      className={`${col.align} py-2 px-3 cursor-pointer select-none hover:text-gray-700 dark:hover:text-slate-200 transition-colors whitespace-nowrap`}
                      onClick={() => toggleSort(col.key)}
                    >
                      {col.label}
                      {"tooltip" in col && col.tooltip && (
                        <Tooltip content={col.tooltip}><InfoIcon /></Tooltip>
                      )}
                      {sortKey === col.key && (
                        <span className="ml-1">{sortDir === "asc" ? "\u25B2" : "\u25BC"}</span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedTrends.map((t) => {
                  const fbTotal = t.feedback_positive + t.feedback_negative;
                  const fbRate = t.total > 0 ? (t.traces_with_feedback / t.total) * 100 : 0;
                  const posRate = fbTotal > 0 ? (t.feedback_positive / fbTotal) * 100 : 0;
                  return (
                    <tr key={t.date} className="border-b border-gray-100 dark:border-slate-800">
                      <td className="py-2 px-3">{t.date}</td>
                      <td className="text-right py-2 px-3">{t.total}</td>
                      <td className="text-right py-2 px-3">{t.unique_users}</td>
                      <td className="text-right py-2 px-3">{t.unique_threads}</td>
                      <td className="text-right py-2 px-3 text-green-500">{t.feedback_positive}</td>
                      <td className="text-right py-2 px-3 text-red-400">{t.feedback_negative}</td>
                      <td className="text-right py-2 px-3">{fbRate.toFixed(1)}%</td>
                      <td className="text-right py-2 px-3">{posRate.toFixed(1)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

    </div>
  );
}
