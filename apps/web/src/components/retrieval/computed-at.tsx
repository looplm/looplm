"use client";

// Shows when a cached metrics result was computed, with a Recompute action to force a fresh run.
export function ComputedAt({
  at,
  onRecompute,
  busy,
}: {
  at?: string | null;
  onRecompute: () => void;
  busy: boolean;
}) {
  return (
    <div className="flex items-center gap-2 text-xs text-gray-400 dark:text-slate-500">
      {at && <span>Computed {formatRelative(at)}</span>}
      <button
        onClick={onRecompute}
        disabled={busy}
        className="inline-flex items-center gap-1 rounded-md border border-gray-200 dark:border-slate-700 px-2 py-0.5 hover:text-gray-600 dark:hover:text-slate-300 disabled:opacity-50"
        title="Recompute now (bypasses the cache)"
      >
        <span className={busy ? "animate-spin" : ""}>↻</span>
        {busy ? "Computing…" : "Recompute"}
      </button>
    </div>
  );
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  return new Date(iso).toLocaleString();
}
