"use client";

import { rootCauseStyle } from "@/app/(app)/evaluations/[id]/eval-utils";
import FilterComboBox from "@/components/filter-combo-box";

interface FailureClassificationSectionProps {
  rootCauseSummary: Record<string, number> | null;
  rootCauseFilter: string[];
  setRootCauseFilter: React.Dispatch<React.SetStateAction<string[]>>;
  failurePatternSummary: Record<string, number> | null;
  patternFilter: string[];
  setPatternFilter: React.Dispatch<React.SetStateAction<string[]>>;
  patternMode: "include" | "exclude";
  setPatternMode: (mode: "include" | "exclude") => void;
}

export function FailureClassificationSection({
  rootCauseSummary,
  rootCauseFilter,
  setRootCauseFilter,
  failurePatternSummary,
  patternFilter,
  setPatternFilter,
  patternMode,
  setPatternMode,
}: FailureClassificationSectionProps) {
  return (
    <>
      {/* Root-cause breakdown (retrieval vs generation vs spec) */}
      {rootCauseSummary && Object.keys(rootCauseSummary).length > 0 && (
        <div className="mb-4 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold">Failure root cause</h3>
            <span className="text-xs text-gray-400 dark:text-slate-500">
              Where failing tests broke — click to filter
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {Object.entries(rootCauseSummary)
              .sort(([, a], [, b]) => b - a)
              .map(([category, count]) => {
                const style = rootCauseStyle(category);
                if (!style) return null;
                const active = rootCauseFilter.includes(category);
                return (
                  <button
                    key={category}
                    onClick={() =>
                      setRootCauseFilter((prev) =>
                        prev.includes(category)
                          ? prev.filter((c) => c !== category)
                          : [...prev, category],
                      )
                    }
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-sm font-medium transition-shadow cursor-pointer ${style.badge} ${
                      active ? "ring-2 ring-indigo-500 dark:ring-indigo-400" : "hover:ring-1 hover:ring-gray-300 dark:hover:ring-slate-600"
                    }`}
                    title={style.description}
                  >
                    {style.label}
                    <span className="font-semibold tabular-nums">{count}</span>
                  </button>
                );
              })}
            {rootCauseFilter.length > 0 && (
              <button
                onClick={() => setRootCauseFilter([])}
                className="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 underline"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      )}

      {/* Failure pattern filter (only when the run has been classified) */}
      {failurePatternSummary && Object.keys(failurePatternSummary).length > 0 && (
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <FilterComboBox
            label="Failure pattern"
            placeholder="Filter by failure pattern..."
            options={Object.entries(failurePatternSummary)
              .sort(([, a], [, b]) => b - a)
              .map(([name, count]) => `${name} (${count})`)
              .concat()}
            selected={patternFilter.map((name) => {
              const count = failurePatternSummary[name];
              return count != null ? `${name} (${count})` : name;
            })}
            onSelectedChange={(values) => {
              // Strip the trailing " (count)" suffix that we add for display.
              setPatternFilter(values.map((v) => v.replace(/\s*\(\d+\)\s*$/, "")));
            }}
            mode={patternMode}
            onModeChange={setPatternMode}
            allowFreeText={false}
          />
          {patternFilter.length > 0 && (
            <button
              onClick={() => setPatternFilter([])}
              className="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 underline mb-1"
            >
              Clear
            </button>
          )}
        </div>
      )}
    </>
  );
}
