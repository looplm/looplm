export const PROMPTS_READ_ONLY_TITLE =
  "Read-only access. Ask an admin to grant write permission.";

export const SOURCE_BADGES: Record<string, string> = {
  langfuse: "bg-purple-500/20 text-purple-700 dark:text-purple-300 border-purple-500/40",
  langsmith: "bg-blue-500/20 text-blue-700 dark:text-blue-300 border-blue-500/40",
  json_import: "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 border-emerald-500/40",
  json_file: "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 border-emerald-500/40",
  github: "bg-gray-800 text-white border-gray-800 dark:bg-slate-200 dark:text-slate-900 dark:border-slate-200",
};

export const SOURCE_LABELS: Record<string, string> = {
  langfuse: "Langfuse",
  langsmith: "LangSmith",
  json_import: "JSON",
  json_file: "JSON",
  github: "GitHub",
};

export const SEVERITY_COLORS: Record<string, string> = {
  high: "text-red-400",
  medium: "text-amber-400",
  low: "text-green-400",
};

export function timeAgo(iso?: string): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const sec = Math.round((Date.now() - then) / 1000);
  if (sec < 60) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.round(hr / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function fmtDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "0s";
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function simpleDiff(a: string, b: string): { left: string[]; right: string[] } {
  const linesA = a.split("\n");
  const linesB = b.split("\n");
  return { left: linesA, right: linesB };
}
