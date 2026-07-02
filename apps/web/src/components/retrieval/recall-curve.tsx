"use client";

import { EXPLAIN, pct } from "./constants";
import { Info } from "./metric-card";

export function RecallCurve({
  recall,
  ks,
  target,
  label = "Recall",
}: {
  recall: Record<string, number>;
  ks: number[];
  target: number | null;
  // Metric name for the title (the values dict is passed in via `recall`).
  label?: string;
}) {
  return (
    <div className="flex flex-col h-full rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
      <div className="flex items-center text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-4">
        {label} @ k
        <Info text={EXPLAIN.recallCurve} />
      </div>

      {/* Plot fills remaining card height; bars size as % of this flex-1 area. */}
      <div className="relative flex-1 min-h-[140px]">
        {[0.25, 0.5, 0.75, 1].map((g) => (
          <div
            key={g}
            className="absolute inset-x-0 border-t border-dashed border-gray-100 dark:border-slate-800"
            style={{ bottom: `${g * 100}%` }}
          />
        ))}
        {target != null && (
          <div
            className="absolute inset-x-0 border-t-2 border-dashed border-emerald-500/70 z-10"
            style={{ bottom: `${Math.min(100, target * 100)}%` }}
          >
            <span className="absolute right-0 -top-4 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
              target {pct(target)}
            </span>
          </div>
        )}
        <div className="absolute inset-0 flex items-end gap-3">
          {ks.map((k) => {
            const v = recall[String(k)] ?? 0;
            const ok = target == null || v >= target;
            return (
              <div key={k} className="group flex-1 h-full flex flex-col justify-end items-center">
                <div className="text-[11px] font-mono font-semibold text-gray-600 dark:text-slate-300 mb-1 tabular-nums">
                  {pct(v)}
                </div>
                <div
                  className={`w-full max-w-[44px] rounded-t-md transition-all ${
                    ok
                      ? "bg-gradient-to-t from-indigo-500 to-indigo-400"
                      : "bg-gradient-to-t from-amber-500 to-amber-400"
                  }`}
                  style={{ height: `${Math.max(1.5, v * 100)}%` }}
                />
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex gap-3 mt-2 pt-2 border-t border-gray-100 dark:border-slate-800">
        {ks.map((k) => (
          <div key={k} className="flex-1 text-center text-[11px] font-mono text-gray-400 dark:text-slate-500">
            @{k}
          </div>
        ))}
      </div>
    </div>
  );
}

export function MiniBar({ v, ok }: { v: number; ok: boolean }) {
  return (
    <div className="flex items-center justify-end gap-2">
      <div className="w-14 h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
        <div
          className={`h-full rounded-full ${ok ? "bg-indigo-500" : "bg-amber-500"}`}
          style={{ width: `${Math.max(2, v * 100)}%` }}
        />
      </div>
      <span className="font-mono tabular-nums text-gray-700 dark:text-slate-300 w-9 text-right">{pct(v)}</span>
    </div>
  );
}
