export default function StatusBadge({ status }: { status?: string }) {
  const colors: Record<string, string> = {
    success: "bg-green-500/20 text-green-400 border-green-500/30",
    failure: "bg-red-500/20 text-red-400 border-red-500/30",
    degraded: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    error: "bg-red-500/20 text-red-400 border-red-500/30",
    idle: "bg-slate-500/20 text-gray-500 dark:text-slate-400 border-slate-500/30",
    syncing: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    never: "bg-slate-500/20 text-gray-500 dark:text-slate-400 border-slate-500/30",
    pending: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    applied: "bg-green-500/20 text-green-400 border-green-500/30",
    dismissed: "bg-slate-500/20 text-gray-500 dark:text-slate-400 border-slate-500/30",
  };

  const color = colors[status || ""] || "bg-slate-500/20 text-gray-500 dark:text-slate-400 border-slate-500/30";

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border ${color}`}>
      {status === "syncing" && (
        <svg className="h-3 w-3 animate-spin" viewBox="0 0 16 16" fill="none">
          <circle className="opacity-25" cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" />
          <path className="opacity-75" d="M14 8a6 6 0 0 0-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      )}
      {status || "unknown"}
    </span>
  );
}
