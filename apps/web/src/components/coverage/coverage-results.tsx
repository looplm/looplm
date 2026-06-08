"use client";

import { StatCard } from "@/components/eval-shared";
import type { CoverageResults } from "@/lib/api";

export function CoverageResultsView({ results }: { results: CoverageResults }) {
  const maxCount = results.rows.reduce((m, r) => Math.max(m, r.indexed_count), 0) || 1;

  return (
    <div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <StatCard
          label="Values covered"
          value={`${results.covered_values}/${results.total_values}`}
          accent={results.covered_values === results.total_values ? "green" : "amber"}
        />
        <StatCard label="Value coverage" value={`${results.value_coverage_pct}%`} />
        <StatCard
          label="Chunk coverage"
          value={`${results.doc_coverage_pct}%`}
          sub="share of indexed chunks in covered values"
        />
        <StatCard
          label="Gaps"
          value={results.total_values - results.covered_values}
          accent={results.total_values - results.covered_values > 0 ? "red" : "green"}
        />
      </div>

      <div className="rounded-xl border border-gray-100 dark:border-slate-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-xs text-gray-500 dark:text-slate-400">
              <th className="px-4 py-2 font-medium">{results.partition_key}</th>
              <th className="px-4 py-2 font-medium text-right">Indexed (chunks)</th>
              <th className="px-4 py-2 font-medium text-right">Test cases</th>
              <th className="px-4 py-2 font-medium text-center">Covered</th>
            </tr>
          </thead>
          <tbody>
            {results.rows.map((r) => (
              <tr
                key={r.value}
                className={`border-b border-gray-50 dark:border-slate-800/50 ${
                  r.covered ? "" : "bg-red-50/40 dark:bg-red-900/10"
                }`}
              >
                <td className="px-4 py-2">
                  <div className="font-medium truncate max-w-[280px]" title={r.value}>
                    {r.value}
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden max-w-[280px]">
                    <div
                      className={`h-full rounded-full ${r.covered ? "bg-indigo-500" : "bg-red-400"}`}
                      style={{ width: `${Math.round((r.indexed_count / maxCount) * 100)}%` }}
                    />
                  </div>
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {r.indexed_count.toLocaleString()}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">{r.covering_cases}</td>
                <td className="px-4 py-2 text-center">{r.covered ? "✅" : "❌"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-gray-400 dark:text-slate-500">
        Counts are per indexed chunk, not distinct documents.
      </p>
    </div>
  );
}
