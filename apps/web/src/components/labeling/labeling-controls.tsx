"use client";

import { PassageOffsetBackfill } from "./passage-offset-backfill";

// The labeling index's controls bar: overall progress (cases complete) and the dataset-level bulk
// actions (recompute every pool, AI-judge every case) kept here as a secondary path — the primary
// flow is per-question in the workbench. Split out so the page stays focused on data + handlers.

// Compact "x ago" for a pool timestamp. Falls back to the locale date past a week. Shared with the
// per-question workbench.
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 45) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days <= 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function LabelingControls({
  complete,
  total,
  canEdit,
  indexConnected,
  bulkBusy,
  bulkProgress,
  onRecomputeAll,
  onAiJudgeAll,
  onJudgeAllDatasets,
  datasetCount,
  onStop,
  includeExpectedAnswer,
  onIncludeExpectedAnswerChange,
  refreshChunks,
  onRefreshChunksChange,
}: {
  complete: number;
  total: number;
  canEdit: boolean;
  indexConnected: boolean;
  // Which bulk action is running (if any), and its progress, so both buttons disable together.
  bulkBusy: "recompute" | "judge" | "judge_all" | null;
  bulkProgress: { done: number; total: number } | null;
  onRecomputeAll: () => void;
  // Judge every question in the currently selected dataset.
  onAiJudgeAll: () => void;
  // Judge every question across all datasets in the project (cross-dataset gold).
  onJudgeAllDatasets: () => void;
  // How many datasets the project has (labels the cross-dataset judge button).
  datasetCount: number;
  // Halt the running bulk action (lets in-flight requests settle, then stops).
  onStop: () => void;
  // Whether the AI judge folds each case's reference answer into its prompt.
  includeExpectedAnswer: boolean;
  onIncludeExpectedAnswerChange: (value: boolean) => void;
  // Whether the AI judge re-queries the index (bypassing the pool cache) before grading.
  refreshChunks: boolean;
  onRefreshChunksChange: (value: boolean) => void;
}) {
  const busy = bulkBusy !== null;
  return (
    <div className="flex items-center gap-3 mb-4 text-xs text-gray-400 dark:text-slate-500">
      <span>
        {complete} / {total} questions complete
      </span>
      <div className="flex-1 max-w-[240px] h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
        <div
          className="h-full rounded-full bg-emerald-500"
          style={{ width: `${total ? (complete / total) * 100 : 0}%` }}
        />
      </div>
      {!canEdit && <span className="text-amber-600 dark:text-amber-400">read-only access</span>}
      {indexConnected && canEdit && (
        <div className="ml-auto flex items-center gap-2">
          {busy ? (
            // While a bulk action runs, collapse the cluster to the running task + a single Stop so
            // it's the only focus. Progress is absent during the cross-dataset enumeration phase.
            <>
              <span>
                {bulkBusy === "recompute" ? "Recomputing" : "Judging"}
                {bulkProgress ? ` ${bulkProgress.done}/${bulkProgress.total}` : ""}…
              </span>
              <button
                onClick={onStop}
                title="Stop — lets in-flight questions finish, then halts."
                className="px-2 py-0.5 rounded-md border border-red-300 dark:border-red-700/60 text-red-600 dark:text-red-300 hover:border-red-400"
              >
                Stop
              </button>
            </>
          ) : (
            <>
              {/* Index re-query — not a judge action, so it sits apart (before the divider) and is
                  unaffected by the "include expected answer" option. */}
              <button
                onClick={onRecomputeAll}
                title="Re-query the index for every question, bypassing the cache. Use after re-indexing."
                className="px-2 py-0.5 rounded-md border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-indigo-400"
              >
                Recompute all
              </button>
              <PassageOffsetBackfill canEdit={canEdit} />
              <span className="h-4 w-px bg-gray-200 dark:bg-slate-700" aria-hidden />
              {/* AI-judge cluster: the shared option, then the two scopes it governs. */}
              <label
                title="Fold each case's reference answer into the AI judge prompt as context. Uncheck to grade on query-relevance alone."
                className="flex items-center gap-1.5 cursor-pointer select-none"
              >
                <input
                  type="checkbox"
                  checked={includeExpectedAnswer}
                  onChange={(e) => onIncludeExpectedAnswerChange(e.target.checked)}
                  className="accent-violet-500"
                />
                Include expected answer
              </label>
              <label
                title="Re-query the index for each question before grading, bypassing the pool cache. Slower (an embedding + index call per question); use after re-indexing. Off grades the already-pooled chunks."
                className="flex items-center gap-1.5 cursor-pointer select-none"
              >
                <input
                  type="checkbox"
                  checked={refreshChunks}
                  onChange={(e) => onRefreshChunksChange(e.target.checked)}
                  className="accent-violet-500"
                />
                Recompute chunks first
              </label>
              <button
                onClick={onAiJudgeAll}
                title="Run the AI judge over every question in the selected dataset (uses the default rubric)."
                className="px-2 py-0.5 rounded-md border border-violet-300 dark:border-violet-700/60 text-violet-600 dark:text-violet-300 hover:border-violet-400"
              >
                ✦ Judge this dataset
              </button>
              <button
                onClick={onJudgeAllDatasets}
                disabled={datasetCount === 0}
                title="Run the AI judge over every question across all datasets in the project. Populates the AI-judge gold everywhere."
                className="px-2 py-0.5 rounded-md border border-violet-300 dark:border-violet-700/60 text-violet-600 dark:text-violet-300 hover:border-violet-400 disabled:opacity-40"
              >
                ✦ Judge all {datasetCount} dataset{datasetCount === 1 ? "" : "s"}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
