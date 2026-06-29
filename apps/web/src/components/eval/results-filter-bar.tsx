"use client";

import type { EvalRunDetail, RerunScope } from "@/lib/api";
import type { Filter } from "@/app/(app)/evaluations/[id]/hooks/use-eval-filters";

interface ResultsFilterBarProps {
  run: EvalRunDetail;
  canEdit: boolean;
  filter: Filter;
  setFilter: (f: Filter) => void;
  computedStats: { total: number; passed: number; failed: number; passRate: number };
  testIdFilter: string | null;
  setTestIdFilter: (v: string | null) => void;
  subsetFilterActive: boolean;
  visibleFailingTestIds: string[];
  rerunningScope: string | null;
  onRerun: (scope?: RerunScope, testIds?: string[]) => void;
  selectedTestIds: Set<string>;
  setSelectedTestIds: (v: Set<string>) => void;
}

export function ResultsFilterBar({
  run,
  canEdit,
  filter,
  setFilter,
  computedStats,
  testIdFilter,
  setTestIdFilter,
  subsetFilterActive,
  visibleFailingTestIds,
  rerunningScope,
  onRerun,
  selectedTestIds,
  setSelectedTestIds,
}: ResultsFilterBarProps) {
  return (
    <>
      {/* Filter */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {(["all", "passed", "failed"] as Filter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-4 py-2 rounded-lg text-base font-medium transition-colors ${
              filter === f
                ? "bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300 border border-indigo-500/30"
                : "text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800 border border-gray-100 dark:border-slate-800"
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
            {f === "all" && ` (${computedStats.total})`}
            {f === "passed" && ` (${computedStats.passed})`}
            {f === "failed" && ` (${computedStats.failed})`}
          </button>
        ))}
        {testIdFilter && (
          <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-700/40">
            Test ID: {testIdFilter}
            <button
              onClick={() => setTestIdFilter(null)}
              className="hover:text-amber-900 dark:hover:text-amber-200"
              aria-label="Clear test ID filter"
            >
              &times;
            </button>
          </span>
        )}
        {run.source === "triggered" && canEdit && subsetFilterActive && visibleFailingTestIds.length > 0 && (
          <button
            onClick={() => onRerun("filtered", visibleFailingTestIds)}
            disabled={rerunningScope !== null}
            title="Rerun the failing test cases matching the current filters as a new linked run"
            className="ml-auto px-4 py-2 rounded-lg text-base font-medium border border-indigo-500 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-600/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {rerunningScope === "filtered"
              ? "Starting..."
              : `Rerun ${visibleFailingTestIds.length} filtered failure${visibleFailingTestIds.length !== 1 ? "s" : ""}`}
          </button>
        )}
      </div>

      {/* Bulk selection bar */}
      {selectedTestIds.size > 0 && (
        <div className="mb-4 flex items-center gap-3 px-4 py-2.5 rounded-xl bg-indigo-50 dark:bg-indigo-600/10 border border-indigo-200 dark:border-indigo-500/30">
          <span className="text-sm font-medium text-indigo-700 dark:text-indigo-300">
            {selectedTestIds.size} test case{selectedTestIds.size !== 1 ? "s" : ""} selected
          </span>
          {run.source === "triggered" && canEdit && (
            <button
              onClick={() => onRerun("selected", Array.from(selectedTestIds))}
              disabled={rerunningScope !== null}
              className="px-3 py-1.5 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {rerunningScope === "selected" ? "Starting..." : "Rerun selected"}
            </button>
          )}
          <button
            onClick={() => setSelectedTestIds(new Set())}
            className="text-sm text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 underline"
          >
            Clear
          </button>
        </div>
      )}
    </>
  );
}
