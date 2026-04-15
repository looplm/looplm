"use client";

import { useEffect, useMemo, useState } from "react";
import { getDashboardStats, type DashboardStats } from "@/lib/api";
import { useGlobalFilters } from "@/components/global-filters-context";
import Tooltip from "@/components/tooltip";
import { UsageTrendChart } from "./usage-trend-chart";

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
  const { startDate, endDate, environment, userFilterMode, filteredUsers } = useGlobalFilters();

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
  }, [startDate, endDate, environment, userFilterMode, filteredUsers]);

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

  const { totals, top_failures, feedback } = stats;

  return (
    <div>
      <h1 className="text-3xl font-bold mb-8">Dashboard</h1>

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        {[
          { label: "Total Traces", value: totals.traces.toLocaleString(), tooltip: "Total number of traces in the selected period" },
          { label: "Unique Users", value: totals.unique_users.toLocaleString(), tooltip: "Number of distinct users who generated traces" },
          { label: "Unique Threads", value: totals.unique_threads.toLocaleString(), tooltip: "Number of distinct conversation threads" },
          {
            label: "Feedback Rate",
            value: totals.traces > 0
              ? `${(((totals.traces - feedback.no_feedback_traces) / totals.traces) * 100).toFixed(1)}%`
              : "0.0%",
            color: "text-green-500",
            tooltip: "Percentage of traces that received at least one feedback score",
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
          </div>
        ))}
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

      {/* Bottom row: Feedback Summary + Top Failures */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6">
          <h2 className="text-lg font-semibold mb-4">Feedback Summary</h2>
          <div className="grid grid-cols-2 gap-4">
            {[
              { label: "Total Feedback", value: feedback.total, tooltip: "Total number of feedback scores (a trace can have multiple)" },
              { label: "Positive", value: feedback.positive, color: "text-green-500", tooltip: "Number of positive feedback scores" },
              { label: "Negative", value: feedback.negative, color: "text-red-400", tooltip: "Number of negative feedback scores" },
              { label: "No Feedback", value: feedback.no_feedback_traces, color: "text-gray-400 dark:text-slate-500", tooltip: "Number of traces that received no feedback" },
            ].map((f) => (
              <div key={f.label}>
                <p className="text-xs text-gray-500 dark:text-slate-400">
                  {f.label}
                  {f.tooltip && <Tooltip content={f.tooltip}><InfoIcon /></Tooltip>}
                </p>
                <p className={`text-2xl font-bold ${f.color || ""}`}>{f.value}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6">
          <h2 className="text-lg font-semibold mb-4">Top Failure Types</h2>
          {top_failures.length === 0 ? (
            <p className="text-gray-500 dark:text-slate-400 text-sm">No failures detected.</p>
          ) : (
            <ul className="space-y-3">
              {top_failures.map((f) => (
                <li key={f.failure_type} className="flex items-center justify-between">
                  <span className="text-sm">{f.failure_type}</span>
                  <span className="text-sm text-gray-500 dark:text-slate-400">{f.count} ({(f.percentage * 100).toFixed(1)}%)</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
