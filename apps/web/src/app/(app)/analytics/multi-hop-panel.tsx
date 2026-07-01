"use client";

import { useEffect, useState } from "react";
import {
  getMultiHopStats,
  type AnalyticsFilters,
  type MultiHopResponse,
  type MultiHopDefinition,
  type HistogramBin,
} from "@/lib/api";

// Distinct tone per logged complexity level for the distribution bar + legend.
const COMPLEXITY_TONES: Record<string, { bar: string; dot: string; label: string }> = {
  simple: { bar: "bg-emerald-400 dark:bg-emerald-500", dot: "bg-emerald-400 dark:bg-emerald-500", label: "Simple" },
  moderate: { bar: "bg-amber-400 dark:bg-amber-500", dot: "bg-amber-400 dark:bg-amber-500", label: "Moderate" },
  complex: { bar: "bg-indigo-500", dot: "bg-indigo-500", label: "Complex" },
  unclassified: { bar: "bg-gray-300 dark:bg-slate-700", dot: "bg-gray-300 dark:bg-slate-700", label: "Unclassified" },
};

function pct(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? "—" : `${Math.round(rate * 100)}%`;
}

export function MultiHopPanel({ filters }: { filters: AnalyticsFilters }) {
  const [data, setData] = useState<MultiHopResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setData(null);
    setFailed(false);
    getMultiHopStats(filters)
      .then(setData)
      .catch(() => setFailed(true));
  }, [filters]);

  if (failed)
    return (
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 text-sm text-gray-400 dark:text-slate-500">
        Could not load multi-hop stats.
      </div>
    );
  if (data === null)
    return (
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 text-sm text-gray-400 dark:text-slate-500">
        Loading…
      </div>
    );
  if (data.requests_total === 0)
    return (
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 text-sm text-gray-400 dark:text-slate-500">
        No requests in this window.
      </div>
    );
  if (data.requests_analyzed === 0)
    return (
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-6 text-sm text-gray-400 dark:text-slate-500">
        No multi-hop signals found. Requests need query-complexity / expanded-query metadata
        or a search span to be measurable.
      </div>
    );

  return (
    <div className="space-y-6">
      <p className="text-xs text-gray-400 dark:text-slate-500">
        {data.requests_analyzed.toLocaleString()} of {data.requests_total.toLocaleString()} requests
        carried a measurable retrieval signal. Each rate is over the requests where that signal
        was observable.
      </p>

      {/* One card per definition of "multi-hop". */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {data.definitions.map((d) => (
          <DefinitionCard key={d.key} def={d} />
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {data.complexity.length > 0 && (
          <div className="lg:col-span-1">
            <h3 className="text-sm font-semibold mb-2 text-gray-700 dark:text-slate-200">
              Query complexity
            </h3>
            <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4">
              <ComplexityBar buckets={data.complexity} />
            </div>
          </div>
        )}
        <Histogram
          title="Queries per request"
          subtitle={
            data.avg_queries_per_request != null
              ? `avg ${data.avg_queries_per_request}`
              : undefined
          }
          bins={data.queries_per_request}
        />
        <Histogram
          title="Search calls per request"
          subtitle={
            data.avg_search_calls_per_request != null
              ? `avg ${data.avg_search_calls_per_request}`
              : undefined
          }
          bins={data.search_calls_per_request}
        />
      </div>
    </div>
  );
}

function DefinitionCard({ def }: { def: MultiHopDefinition }) {
  const hasData = def.total > 0;
  return (
    <div
      className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4 flex flex-col"
      title={def.description}
    >
      <div className="text-2xl font-semibold text-gray-900 dark:text-slate-100">
        {pct(def.rate)}
      </div>
      <div className="text-sm font-medium text-gray-700 dark:text-slate-200 mt-0.5">{def.label}</div>
      <div className="text-xs text-gray-400 dark:text-slate-500 mt-0.5">
        {hasData ? `${def.multi_hop.toLocaleString()} / ${def.total.toLocaleString()} requests` : "no data"}
      </div>
      <div className="mt-2 h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
        <div
          className="h-full bg-indigo-500"
          style={{ width: `${Math.round((def.rate ?? 0) * 100)}%` }}
        />
      </div>
      <p className="text-[11px] leading-snug text-gray-400 dark:text-slate-500 mt-2">
        {def.description}
      </p>
    </div>
  );
}

function ComplexityBar({ buckets }: { buckets: { level: string; count: number }[] }) {
  const total = buckets.reduce((s, b) => s + b.count, 0) || 1;
  return (
    <div>
      <div className="flex h-3 rounded-full overflow-hidden mb-3">
        {buckets.map((b) => {
          const tone = COMPLEXITY_TONES[b.level] ?? COMPLEXITY_TONES.unclassified;
          return (
            <div
              key={b.level}
              className={tone.bar}
              style={{ width: `${(b.count / total) * 100}%` }}
              title={`${tone.label}: ${b.count}`}
            />
          );
        })}
      </div>
      <ul className="space-y-1.5">
        {buckets.map((b) => {
          const tone = COMPLEXITY_TONES[b.level] ?? COMPLEXITY_TONES.unclassified;
          return (
            <li key={b.level} className="flex items-center gap-2 text-xs">
              <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${tone.dot}`} />
              <span className="text-gray-600 dark:text-slate-300 flex-1">{tone.label}</span>
              <span className="text-gray-400 dark:text-slate-500">{b.count.toLocaleString()}</span>
              <span className="text-gray-300 dark:text-slate-600 w-9 text-right">
                {Math.round((b.count / total) * 100)}%
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Histogram({
  title,
  subtitle,
  bins,
}: {
  title: string;
  subtitle?: string;
  bins: HistogramBin[];
}) {
  const max = Math.max(1, ...bins.map((b) => b.count));
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">{title}</h3>
        {subtitle && <span className="text-xs text-gray-400 dark:text-slate-500">{subtitle}</span>}
      </div>
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4">
        {bins.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-slate-500">No data in this window.</p>
        ) : (
          <div className="flex gap-2 items-end h-24">
            {bins.map((b) => (
              <div key={b.value} className="flex-1 flex flex-col items-center justify-end gap-1">
                <span className="text-[11px] text-gray-400 dark:text-slate-500">{b.count}</span>
                <div
                  className="w-full rounded-t-sm bg-indigo-500"
                  style={{ height: `${Math.round((b.count / max) * 100)}%`, minHeight: 3 }}
                  title={`${b.label}: ${b.count}`}
                />
                <span className="text-[11px] text-gray-500 dark:text-slate-400">{b.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
