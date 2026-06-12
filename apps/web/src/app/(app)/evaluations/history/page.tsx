"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  getDatasetsPicker,
  getTestCaseHistory,
  type DatasetPickerItem,
  type TestCaseHistoryItem,
  type TestCaseHistoryResponse,
} from "@/lib/api";
import { rootCauseStyle } from "../[id]/eval-utils";

type SortColumn = "test_id" | "dataset" | "runs" | "failures" | "pass_rate" | "last_failed";
type SortDirection = "asc" | "desc";

const RUN_LIMITS = [10, 20, 50, 100];

function passRateColor(rate: number): string {
  if (rate >= 0.9) return "bg-green-500";
  if (rate >= 0.6) return "bg-amber-500";
  return "bg-red-500";
}

function TrendDots({ item }: { item: TestCaseHistoryItem }) {
  return (
    <div className="flex items-center gap-1">
      {(item.trend ?? []).map((p) => (
        <Link
          key={p.run_id}
          href={`/evaluations/${p.run_id}?test_id=${encodeURIComponent(item.test_id)}`}
          className={`inline-block w-2.5 h-2.5 rounded-full transition-transform hover:scale-150 ${
            p.passed ? "bg-green-500" : "bg-red-500"
          } ${p.is_rerun ? "ring-1 ring-offset-1 ring-indigo-400 dark:ring-offset-slate-900" : ""}`}
          title={`${new Date(p.created_at).toLocaleString()} — ${p.passed ? "passed" : "failed"}${p.is_rerun ? " (rerun)" : ""}`}
        />
      ))}
    </div>
  );
}

export default function TestCaseHistoryPage() {
  const [resp, setResp] = useState<TestCaseHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [datasets, setDatasets] = useState<DatasetPickerItem[]>([]);
  const [datasetFilter, setDatasetFilter] = useState<string>("all");
  const [runLimit, setRunLimit] = useState(20);
  const [minFailures, setMinFailures] = useState(0);
  const [includeReruns, setIncludeReruns] = useState(true);
  const [search, setSearch] = useState("");
  const [sortCol, setSortCol] = useState<SortColumn>("failures");
  const [sortDir, setSortDir] = useState<SortDirection>("desc");

  useEffect(() => {
    getDatasetsPicker()
      .then((d) => setDatasets(d.datasets))
      .catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const params: Record<string, string> = {
      run_limit: String(runLimit),
      min_failures: String(minFailures),
      include_reruns: String(includeReruns),
    };
    if (datasetFilter !== "all") params.dataset_id = datasetFilter;
    getTestCaseHistory(params)
      .then(setResp)
      .catch((err: any) => setError(err?.message || "Failed to load test case history"))
      .finally(() => setLoading(false));
  }, [datasetFilter, runLimit, minFailures, includeReruns]);

  const toggleSort = (col: SortColumn) => {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir(col === "test_id" || col === "dataset" ? "asc" : "desc");
    }
  };

  const rows = useMemo(() => {
    if (!resp) return [];
    let items = resp.data;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      items = items.filter((i) => i.test_id.toLowerCase().includes(q));
    }
    const dir = sortDir === "asc" ? 1 : -1;
    return [...items].sort((a, b) => {
      switch (sortCol) {
        case "test_id":
          return dir * a.test_id.localeCompare(b.test_id);
        case "dataset":
          return dir * (a.dataset_name || "").localeCompare(b.dataset_name || "");
        case "runs":
          return dir * (a.runs_participated - b.runs_participated);
        case "failures":
          return dir * (a.fail_count - b.fail_count);
        case "pass_rate":
          return dir * (a.pass_rate - b.pass_rate);
        case "last_failed":
          return dir * ((a.last_failed_at || "").localeCompare(b.last_failed_at || ""));
      }
    });
  }, [resp, search, sortCol, sortDir]);

  const sortIcon = (col: SortColumn) =>
    sortCol === col ? (
      <span className="inline-block ml-1 text-indigo-500 dark:text-indigo-400">{sortDir === "asc" ? "▲" : "▼"}</span>
    ) : (
      <span className="inline-block ml-1 text-gray-300 dark:text-slate-600">▲</span>
    );

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Dataset</label>
          <select
            value={datasetFilter}
            onChange={(e) => setDatasetFilter(e.target.value)}
            className="px-3 py-2 rounded-lg text-sm bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700"
          >
            <option value="all">All datasets</option>
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Run window</label>
          <select
            value={runLimit}
            onChange={(e) => setRunLimit(Number(e.target.value))}
            className="px-3 py-2 rounded-lg text-sm bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700"
          >
            {RUN_LIMITS.map((n) => (
              <option key={n} value={n}>Last {n} runs</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Min failures</label>
          <input
            type="number"
            min={0}
            value={minFailures}
            onChange={(e) => setMinFailures(Math.max(0, Number(e.target.value)))}
            className="w-24 px-3 py-2 rounded-lg text-sm bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1">Search</label>
          <input
            type="text"
            placeholder="Filter by test ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-56 px-3 py-2 rounded-lg text-sm bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700"
          />
        </div>
        <label className="flex items-center gap-2 pb-2 cursor-pointer">
          <input
            type="checkbox"
            checked={includeReruns}
            onChange={(e) => setIncludeReruns(e.target.checked)}
            className="rounded border-gray-300 dark:border-slate-600"
          />
          <span className="text-sm text-gray-600 dark:text-slate-300">Include partial reruns</span>
        </label>
        {resp && (
          <span className="ml-auto pb-2 text-xs text-gray-400 dark:text-slate-500">
            {resp.runs_considered} run{resp.runs_considered !== 1 ? "s" : ""} considered
            {resp.oldest_run_at && ` since ${new Date(resp.oldest_run_at).toLocaleDateString()}`}
          </span>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-gray-500 dark:text-slate-400">Loading...</p>
      ) : rows.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          No test case history matches the current filters.
        </div>
      ) : (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-white dark:bg-slate-900">
              <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
                {([
                  ["test_id", "Test ID"],
                  ["dataset", "Dataset"],
                  ["runs", "Runs"],
                  ["failures", "Failures"],
                  ["pass_rate", "Pass Rate"],
                ] as [SortColumn, string][]).map(([col, label]) => (
                  <th
                    key={col}
                    className="px-4 py-3 font-medium cursor-pointer select-none hover:text-gray-700 dark:hover:text-slate-200 transition-colors"
                    onClick={() => toggleSort(col)}
                  >
                    {label}
                    {sortIcon(col)}
                  </th>
                ))}
                <th className="px-4 py-3 font-medium">Dominant Pattern</th>
                <th className="px-4 py-3 font-medium">Root Cause</th>
                <th className="px-4 py-3 font-medium">Trend (newest first)</th>
                <th
                  className="px-4 py-3 font-medium cursor-pointer select-none hover:text-gray-700 dark:hover:text-slate-200 transition-colors"
                  onClick={() => toggleSort("last_failed")}
                >
                  Last Failed
                  {sortIcon("last_failed")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => {
                const rc = rootCauseStyle(item.dominant_root_cause);
                return (
                  <tr
                    key={item.test_id}
                    className="border-b border-gray-100/50 dark:border-slate-800/50 hover:bg-gray-100/50 dark:hover:bg-slate-800/30"
                  >
                    <td className="px-4 py-3">
                      <span className="font-medium">{item.test_id}</span>
                      {!item.exists && (
                        <span className="ml-2 px-1.5 py-0.5 rounded text-xs bg-gray-100 dark:bg-slate-800 text-gray-400 dark:text-slate-500" title="This test case no longer exists in any dataset">
                          deleted
                        </span>
                      )}
                      {item.case_status === "needs_work" && (
                        <span className="ml-2 px-1.5 py-0.5 rounded text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400">
                          needs work
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-slate-400">{item.dataset_name || "—"}</td>
                    <td className="px-4 py-3 tabular-nums">{item.runs_participated}</td>
                    <td className="px-4 py-3">
                      <span className={`tabular-nums font-semibold ${item.fail_count > 0 ? "text-red-600 dark:text-red-400" : "text-gray-400 dark:text-slate-500"}`}>
                        {item.fail_count}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 rounded-full bg-gray-200 dark:bg-slate-700 overflow-hidden">
                          <div
                            className={`h-full ${passRateColor(item.pass_rate)}`}
                            style={{ width: `${item.pass_rate * 100}%` }}
                          />
                        </div>
                        <span className="tabular-nums text-gray-600 dark:text-slate-300">
                          {(item.pass_rate * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {item.dominant_failure_pattern ? (
                        <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400">
                          {item.dominant_failure_pattern} ({item.dominant_failure_pattern_count})
                        </span>
                      ) : item.unclassified_failures > 0 ? (
                        <span className="text-xs text-gray-400 dark:text-slate-500" title="Run 'Classify failures' on the failing runs to populate this">
                          unclassified
                        </span>
                      ) : (
                        <span className="text-gray-300 dark:text-slate-600">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {rc ? (
                        <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${rc.badge}`} title={rc.description}>
                          {rc.label} ({item.dominant_root_cause_count})
                        </span>
                      ) : (
                        <span className="text-gray-300 dark:text-slate-600">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <TrendDots item={item} />
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-slate-400 whitespace-nowrap">
                      {item.last_failed_at && item.last_failed_run_id ? (
                        <Link
                          href={`/evaluations/${item.last_failed_run_id}?test_id=${encodeURIComponent(item.test_id)}`}
                          className="text-indigo-600 dark:text-indigo-400 hover:underline"
                        >
                          {new Date(item.last_failed_at).toLocaleDateString()}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
