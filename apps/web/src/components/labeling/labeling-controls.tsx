"use client";

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
}: {
  complete: number;
  total: number;
  canEdit: boolean;
  indexConnected: boolean;
  // Which bulk action is running (if any), and its progress, so both buttons disable together.
  bulkBusy: "recompute" | "judge" | null;
  bulkProgress: { done: number; total: number } | null;
  onRecomputeAll: () => void;
  onAiJudgeAll: () => void;
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
          {busy && bulkProgress && (
            <span>
              {bulkBusy === "judge" ? "Judging" : "Recomputing"} {bulkProgress.done}/{bulkProgress.total}…
            </span>
          )}
          <button
            onClick={onRecomputeAll}
            disabled={busy}
            title="Re-query the index for every question, bypassing the cache. Use after re-indexing."
            className="px-2 py-0.5 rounded-md border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-indigo-400 disabled:opacity-40"
          >
            Recompute all
          </button>
          <button
            onClick={onAiJudgeAll}
            disabled={busy}
            title="Run the AI judge over every question's chunks (uses the default rubric)."
            className="px-2 py-0.5 rounded-md border border-violet-300 dark:border-violet-700/60 text-violet-600 dark:text-violet-300 hover:border-violet-400 disabled:opacity-40"
          >
            ✦ AI-judge all
          </button>
        </div>
      )}
    </div>
  );
}
