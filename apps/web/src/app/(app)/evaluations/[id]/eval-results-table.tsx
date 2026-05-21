"use client";

import { useMemo, useState } from "react";
import type { EvalResultSummary, EvaluatorItem } from "@/lib/api";
import { sortGraderEntries, graderDisplayName } from "./eval-utils";

type SortColumn = "test_id" | "result" | "summary" | "graders";
type SortDirection = "asc" | "desc";
type SortEntry = { col: SortColumn; dir: SortDirection };

function SortIcon({ entry, index, totalSorts }: { entry: SortEntry | undefined; index: number; totalSorts: number }) {
  if (!entry) {
    return <span className="inline-block ml-1 text-gray-300 dark:text-slate-600">▲</span>;
  }
  return (
    <span className="inline-block ml-1 text-indigo-500 dark:text-indigo-400">
      {entry.dir === "asc" ? "▲" : "▼"}
      {totalSorts > 1 && <sup className="text-[10px] ml-0.5">{index + 1}</sup>}
    </span>
  );
}

interface EvalResultsTableProps {
  filteredResults: EvalResultSummary[];
  disabledGraders: Set<string>;
  evaluatorMap: Record<string, EvaluatorItem>;
  onSelectResult: (result: EvalResultSummary) => void;
  loadingResultId?: string | null;
}

export function EvalResultsTable({
  filteredResults,
  disabledGraders,
  evaluatorMap,
  onSelectResult,
  loadingResultId,
}: EvalResultsTableProps) {
  const defaultSort: SortEntry[] = [
    { col: "result", dir: "desc" },
    { col: "summary", dir: "asc" },
  ];
  const [sorts, setSorts] = useState<SortEntry[]>(defaultSort);

  const toggleSort = (col: SortColumn, shiftKey: boolean) => {
    setSorts((prev) => {
      const idx = prev.findIndex((s) => s.col === col);
      if (shiftKey) {
        // Multi-sort: toggle existing or append
        if (idx >= 0) {
          const updated = [...prev];
          updated[idx] = { col, dir: prev[idx].dir === "asc" ? "desc" : "asc" };
          return updated;
        }
        return [...prev, { col, dir: "asc" }];
      }
      // Single sort: replace all
      if (idx >= 0 && prev.length === 1) {
        return [{ col, dir: prev[0].dir === "asc" ? "desc" : "asc" }];
      }
      return [{ col, dir: "asc" }];
    });
  };

  const getFailedCount = (result: EvalResultSummary) => {
    const entries = Object.entries(result.graders || {});
    return entries.filter(([n, g]) => !disabledGraders.has(n) && !g.pass && !g.skipped).length;
  };

  const compareByCol = (a: EvalResultSummary, b: EvalResultSummary, col: SortColumn): number => {
    switch (col) {
      case "test_id":
        return (a.test_id || "").localeCompare(b.test_id || "");
      case "result":
        return (a.pass ? 1 : 0) - (b.pass ? 1 : 0);
      case "summary":
      case "graders":
        return getFailedCount(a) - getFailedCount(b);
    }
  };

  const sortedResults = useMemo(() => {
    return [...filteredResults].sort((a, b) => {
      for (const { col, dir } of sorts) {
        const cmp = compareByCol(a, b, col);
        if (cmp !== 0) return dir === "asc" ? cmp : -cmp;
      }
      return 0;
    });
  }, [filteredResults, sorts, disabledGraders]);

  if (filteredResults.length === 0) {
    return (
      <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
        No results match the current filter.
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-x-auto">
      <table className="w-full text-base">
        <thead className="sticky top-0 z-10 bg-white dark:bg-slate-900">
          <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
            {([
              ["test_id", "Test ID", ""],
              ["result", "Result", "w-20 text-center"],
              ["summary", "Summary", ""],
              ["graders", "Graders", ""],
            ] as [SortColumn, string, string][]).map(([col, label, extra]) => {
              const sortIdx = sorts.findIndex((s) => s.col === col);
              return (
                <th
                  key={col}
                  className={`px-4 py-3 font-medium cursor-pointer select-none hover:text-gray-700 dark:hover:text-slate-200 transition-colors ${extra}`}
                  onClick={(e) => toggleSort(col, e.shiftKey)}
                >
                  {label}
                  <SortIcon entry={sortIdx >= 0 ? sorts[sortIdx] : undefined} index={sortIdx} totalSorts={sorts.length} />
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sortedResults.map((result) => {
            const graderEntries = Object.entries(result.graders || {});
            const sortedGraderEntries = sortGraderEntries(graderEntries, evaluatorMap);
            const isLoading = loadingResultId === result.id;
            return (
              <tr
                key={result.id}
                onClick={() => !loadingResultId && onSelectResult(result)}
                className={`border-b border-gray-100/50 dark:border-slate-800/50 hover:bg-gray-100/50 dark:hover:bg-slate-800/30 ${
                  loadingResultId ? "cursor-wait" : "cursor-pointer"
                } ${isLoading ? "opacity-60" : ""}`}
              >
                <td className="px-4 py-3 text-sm">{result.test_id}</td>
                <td className="px-4 py-3 text-center">
                  <div className="flex items-center justify-center gap-1.5">
                    {result.pass ? (
                      <span className="inline-block px-2 py-0.5 rounded text-sm font-medium bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                        PASS
                      </span>
                    ) : (
                      <span className="inline-block px-2 py-0.5 rounded text-sm font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400">
                        FAIL
                      </span>
                    )}
                    {result.turns_to_pass != null && result.turns_to_pass > 1 && (
                      <span
                        className="inline-block px-1.5 py-0.5 rounded text-xs font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400"
                        title={`Passed on turn ${result.turns_to_pass}`}
                      >
                        T{result.turns_to_pass}
                      </span>
                    )}
                    {result.turn_count != null && result.turn_count > 1 && !result.pass && (
                      <span
                        className="inline-block px-1.5 py-0.5 rounded text-xs font-medium bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400"
                        title={`Failed after ${result.turn_count} turns`}
                      >
                        T{result.turn_count}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3 text-sm text-gray-500 dark:text-slate-400">
                  {(() => {
                    const active = sortedGraderEntries.filter(([n]) => !disabledGraders.has(n));
                    const failed = active.filter(([, g]) => !g.pass && !g.skipped);
                    const skipped = active.filter(([, g]) => g.skipped);
                    if (failed.length === 0) return <span className="text-green-600 dark:text-green-400">All passed</span>;
                    return (
                      <span>
                        <span className="text-red-600 dark:text-red-400 font-medium">{failed.length} failed</span>
                        {" / "}
                        {active.length - skipped.length} graders
                      </span>
                    );
                  })()}
                </td>
                <td className="px-4 py-3">
                  {(() => {
                    const active = sortedGraderEntries.filter(([n]) => !disabledGraders.has(n));
                    const failed = active.filter(([, g]) => !g.pass && !g.skipped);
                    const skipped = active.filter(([, g]) => g.skipped);
                    const passed = active.filter(([, g]) => g.pass && !g.skipped);
                    return (
                      <div className="flex gap-1 flex-wrap">
                        {failed.map(([name, g]) => (
                          <span
                            key={name}
                            className="inline-block px-2 py-0.5 rounded text-sm bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400"
                            title={g.reason || name}
                          >
                            {graderDisplayName(name, evaluatorMap)}
                          </span>
                        ))}
                        {skipped.length > 0 && (
                          <span
                            className="inline-block px-2 py-0.5 rounded text-sm bg-gray-100 dark:bg-slate-800 text-gray-400 dark:text-slate-500"
                            title={skipped.map(([n]) => graderDisplayName(n, evaluatorMap)).join(", ")}
                          >
                            +{skipped.length} skipped
                          </span>
                        )}
                        {passed.length > 0 && (
                          <span
                            className="inline-block px-2 py-0.5 rounded text-sm bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                            title={passed.map(([n]) => graderDisplayName(n, evaluatorMap)).join(", ")}
                          >
                            +{passed.length} passed
                          </span>
                        )}
                      </div>
                    );
                  })()}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
