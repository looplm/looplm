"use client";

import { useMemo, useState } from "react";

import type { CoverageRunSummary } from "@/lib/api";

function fmt(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function CoverageHistory({
  runs,
  onOpen,
}: {
  runs: CoverageRunSummary[];
  onOpen: (runId: string) => void;
}) {
  const [keyFilter, setKeyFilter] = useState<string>("");

  const keys = useMemo(
    () => Array.from(new Set(runs.map((r) => r.partition_key))).sort(),
    [runs],
  );
  const filtered = keyFilter ? runs.filter((r) => r.partition_key === keyFilter) : runs;

  if (runs.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-gray-200 dark:border-slate-700 p-8 text-center text-sm text-gray-500 dark:text-slate-400">
        No past runs for this provider yet.
      </div>
    );
  }

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <span className="text-xs text-gray-500 dark:text-slate-400">Filter by category</span>
        <select
          value={keyFilter}
          onChange={(e) => setKeyFilter(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 text-sm"
        >
          <option value="">All</option>
          {keys.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </div>

      <div className="rounded-xl border border-gray-100 dark:border-slate-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-xs text-gray-500 dark:text-slate-400">
              <th className="px-4 py-2 font-medium">Category</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium text-right">Coverage</th>
              <th className="px-4 py-2 font-medium text-right">Gaps</th>
              <th className="px-4 py-2 font-medium">When</th>
              <th className="px-4 py-2 font-medium text-right"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.id} className="border-b border-gray-50 dark:border-slate-800/50">
                <td className="px-4 py-2 font-medium">{r.partition_key}</td>
                <td className="px-4 py-2 text-gray-500 dark:text-slate-400">{r.status}</td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {r.value_coverage_pct != null ? `${r.value_coverage_pct}%` : "—"}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">{r.gaps}</td>
                <td className="px-4 py-2 text-gray-500 dark:text-slate-400">{fmt(r.created_at)}</td>
                <td className="px-4 py-2 text-right">
                  {r.status === "completed" && (
                    <button
                      onClick={() => onOpen(r.id)}
                      className="px-2.5 py-1 rounded-lg text-xs bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700"
                    >
                      Open
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
