import type { EvalJob } from "@/lib/api";

const STAT_ACCENTS = {
  green: "border-l-4 border-l-green-500 dark:border-l-green-400",
  red: "border-l-4 border-l-red-500 dark:border-l-red-400",
  amber: "border-l-4 border-l-amber-500 dark:border-l-amber-400",
} as const;

export function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: "green" | "red" | "amber";
}) {
  return (
    <div
      className={`p-5 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 ${
        accent ? STAT_ACCENTS[accent] : ""
      }`}
    >
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-1">{label}</p>
      <p className="text-2xl font-bold">{value}</p>
      {sub && <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">{sub}</p>}
    </div>
  );
}

export function JobStatusBadge({ status }: { status: EvalJob["status"] }) {
  const styles: Record<string, string> = {
    pending: "bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400",
    running: "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400",
    batch_pending: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400",
    completed: "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400",
    failed: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400",
    cancelled: "bg-gray-100 dark:bg-gray-900/30 text-gray-700 dark:text-gray-400",
  };
  const labels: Record<string, string> = {
    batch_pending: "batch processing",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${styles[status] || styles.pending}`}>
      {labels[status] || status}
    </span>
  );
}

export function formatDuration(startedAt: string, completedAt?: string): string {
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const seconds = Math.floor((end - start) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds}s`;
}

export function JobProgressBar({ job }: { job: EvalJob }) {
  if (job.status !== "running" && job.status !== "pending" && job.status !== "batch_pending") return null;
  const hasProgress = job.progress_current != null && job.progress_total != null && job.progress_total > 0;
  const pct = hasProgress ? Math.round((job.progress_current! / job.progress_total!) * 100) : 0;

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-gray-200 dark:bg-slate-700 overflow-hidden max-w-[120px]">
        {hasProgress ? (
          <div
            className="h-full rounded-full bg-blue-500 transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        ) : (
          <div className="h-full rounded-full bg-blue-500/50 animate-pulse w-full" />
        )}
      </div>
      {hasProgress && (
        <span className="text-xs text-gray-500 dark:text-slate-400">
          {job.progress_current}/{job.progress_total}
        </span>
      )}
    </div>
  );
}
