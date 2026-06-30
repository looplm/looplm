"use client";

// The labeling page's top controls bar: overall progress, pool freshness + recompute, and
// collapse/expand. Split out of the page so the page component stays focused on data + handlers.

// Compact "x ago" for the last-pooled timestamp. Falls back to the locale date past a week.
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
  progress,
  canEdit,
  indexConnected,
  pooling,
  lastPooledAt,
  poolHeadsFailed,
  recomputing,
  onRecompute,
  onCollapseAll,
  onExpandAll,
}: {
  progress: { labeled: number; total: number };
  canEdit: boolean;
  indexConnected: boolean;
  pooling: boolean;
  lastPooledAt: string | null;
  poolHeadsFailed: Record<string, string>;
  recomputing: boolean;
  onRecompute: () => void;
  onCollapseAll: () => void;
  onExpandAll: () => void;
}) {
  return (
    <div className="flex items-center gap-3 mb-4 text-xs text-gray-400 dark:text-slate-500">
      <span>
        {progress.labeled} / {progress.total} pooled chunks labeled
      </span>
      <div className="flex-1 max-w-[240px] h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
        <div
          className="h-full rounded-full bg-indigo-500"
          style={{ width: `${progress.total ? (progress.labeled / progress.total) * 100 : 0}%` }}
        />
      </div>
      {!canEdit && <span className="text-amber-600 dark:text-amber-400">read-only access</span>}
      <div className="ml-auto flex items-center gap-3">
        {indexConnected && (
          <div className="flex items-center gap-2">
            <span title="Candidates are pooled live from the index. Shows the oldest pool across cases.">
              {pooling ? "Pooling…" : lastPooledAt ? `Pooled ${relativeTime(lastPooledAt)}` : "Not pooled"}
            </span>
            {Object.keys(poolHeadsFailed).length > 0 && (
              <span
                className="text-amber-600 dark:text-amber-400"
                title={Object.entries(poolHeadsFailed)
                  .map(([h, r]) => `${h}: ${r}`)
                  .join("\n")}
              >
                {Object.keys(poolHeadsFailed).join(", ")} unavailable
              </span>
            )}
            <button
              onClick={onRecompute}
              disabled={recomputing || pooling}
              title="Re-query the index for every case, bypassing the cache. Use after re-indexing."
              className="px-2 py-0.5 rounded-md border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:border-indigo-400 disabled:opacity-40"
            >
              {recomputing ? "Recomputing…" : "Recompute"}
            </button>
          </div>
        )}
        <button onClick={onCollapseAll} className="hover:text-gray-600 dark:hover:text-slate-300">
          Collapse all
        </button>
        <button onClick={onExpandAll} className="hover:text-gray-600 dark:hover:text-slate-300">
          Expand all
        </button>
      </div>
    </div>
  );
}
