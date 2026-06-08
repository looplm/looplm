/**
 * Shared display helpers for the issues feature: badge colors, signal labels,
 * and relative-time formatting.
 */

export const SEVERITY_BADGE: Record<string, string> = {
  high: "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-300",
  medium: "bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300",
  low: "bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-slate-300",
};

export const STATUS_BADGE: Record<string, string> = {
  open: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300",
  diagnosing: "bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300",
  resolving: "bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300",
  recurring: "bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300",
  resolved: "bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-300",
  dismissed: "bg-gray-100 text-gray-500 dark:bg-slate-800 dark:text-slate-400",
};

export const SIGNAL_LABEL: Record<string, string> = {
  explicit_failure: "Failure",
  eval_failure: "Eval failure",
  negative_feedback: "Negative feedback",
  anomaly: "Latency anomaly",
  refusal: "Refusal",
  user_frustration: "User frustration",
  task_incomplete: "Task incomplete",
  loop: "Loop",
};

export function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffMs = Date.now() - then;
  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  if (day < 30) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString();
}
