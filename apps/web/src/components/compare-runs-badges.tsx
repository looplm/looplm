"use client";

export function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatScore(value: number) {
  return value.toFixed(2);
}

function passRateColor(rate: number) {
  if (rate >= 0.8) return "bg-green-500";
  if (rate >= 0.5) return "bg-yellow-500";
  return "bg-red-500";
}

export function DeltaBadge({ current, previous, isPercent }: { current?: number; previous?: number; isPercent?: boolean }) {
  if (current == null || previous == null) {
    return <span className="text-xs text-gray-300 dark:text-slate-600">--</span>;
  }
  const delta = current - previous;
  if (Math.abs(delta) < 0.0005) {
    return <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400">=</span>;
  }
  const positive = delta > 0;
  const arrow = positive ? "↑" : "↓";
  const formatted = isPercent
    ? `${positive ? "+" : ""}${(delta * 100).toFixed(1)}pp`
    : `${positive ? "+" : ""}${delta.toFixed(2)}`;

  return (
    <span className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-medium ${
      positive
        ? "bg-green-50 dark:bg-green-950/40 text-green-700 dark:text-green-400"
        : "bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-400"
    }`}>
      {arrow} {formatted}
    </span>
  );
}

export function MiniBar({ rate }: { rate: number }) {
  return (
    <div className="h-1.5 rounded-full bg-gray-200 dark:bg-slate-700 overflow-hidden mt-1">
      <div
        className={`h-full rounded-full ${passRateColor(rate)}`}
        style={{ width: `${rate * 100}%` }}
      />
    </div>
  );
}

export function SourceBadge({ source }: { source: string | null }) {
  if (!source) return null;
  const styles = source === "ragas"
    ? "bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400"
    : source === "langfuse"
    ? "bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400"
    : "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400";
  const label = source === "ragas" ? "RAGAS" : source === "langfuse" ? "Langfuse" : "Custom";
  return <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${styles}`}>{label}</span>;
}

export function RelevanceBadge({ relevance }: { relevance: string }) {
  const styles = relevance === "core"
    ? "bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400"
    : relevance === "important"
    ? "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400"
    : "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400";
  return <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium capitalize ${styles}`}>{relevance}</span>;
}

export function PassFailBadge({ affectsPass }: { affectsPass: boolean }) {
  if (affectsPass) {
    return (
      <span className="text-green-600 dark:text-green-400" title="Affects pass/fail">
        <svg className="w-3.5 h-3.5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      </span>
    );
  }
  return <span className="text-gray-400 dark:text-slate-600 text-xs">–</span>;
}
