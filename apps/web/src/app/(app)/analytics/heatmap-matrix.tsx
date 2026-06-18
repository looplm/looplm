"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { RequestClusterTheme, RequestOutcome } from "@/lib/api";

type Mode = "count" | "rate";

interface Column {
  key: keyof RequestOutcome;
  label: string;
  /** Tailwind-free RGB triplet for the cell tint. */
  rgb: string;
}

// Outcome columns (status) + a visual divider before the feedback columns.
// "degraded" is intentionally omitted: no connector ever emits that status, so
// the column was always empty (status is a technical execution signal, not a
// quality one — the feedback columns carry the quality signal).
const COLUMNS: Column[] = [
  { key: "success", label: "Success", rgb: "34,197,94" },
  { key: "failure", label: "Failure", rgb: "239,68,68" },
  { key: "fb_positive", label: "👍", rgb: "34,197,94" },
  { key: "fb_negative", label: "👎", rgb: "239,68,68" },
];

// Index of the first feedback column — drives the divider border between the
// status columns and the feedback columns.
const FEEDBACK_DIVIDER_COL = COLUMNS.findIndex((c) => c.key === "fb_positive");

export function HeatmapMatrix({ themes }: { themes: RequestClusterTheme[] }) {
  const [mode, setMode] = useState<Mode>("count");
  const [hover, setHover] = useState<{ row: number; col: number } | null>(null);

  // Per-column maxima drive the "count" intensity so each outcome column is
  // comparable across request types.
  const colMax = useMemo(() => {
    const m: Record<string, number> = {};
    for (const c of COLUMNS) {
      m[c.key] = Math.max(1, ...themes.map((t) => t.outcome?.[c.key] ?? 0));
    }
    return m;
  }, [themes]);

  if (themes.length === 0) return null;

  const intensity = (col: Column, theme: RequestClusterTheme): number => {
    const v = theme.outcome?.[col.key] ?? 0;
    if (mode === "rate") {
      return theme.count > 0 ? v / theme.count : 0;
    }
    return v / colMax[col.key];
  };

  return (
    <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-4 overflow-x-auto">
      <div className="flex items-center justify-between mb-4">
        <p className="text-xs text-gray-500 dark:text-slate-400">
          Each row is a request type; cells show{" "}
          {mode === "count"
            ? "absolute counts, shaded per outcome"
            : "each outcome as a share of that request type"}.
        </p>
        <div className="flex rounded-lg border border-gray-200 dark:border-slate-700 overflow-hidden text-xs">
          {(["count", "rate"] as Mode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1 transition-colors ${
                mode === m
                  ? "bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300"
                  : "text-gray-500 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800"
              }`}
            >
              {m === "count" ? "Absolute" : "Percentage"}
            </button>
          ))}
        </div>
      </div>

      <div className="min-w-[640px]">
        {/* Header row */}
        <div className="grid items-end gap-1 mb-1" style={{ gridTemplateColumns: `minmax(180px,2fr) repeat(${COLUMNS.length}, minmax(64px,1fr))` }}>
          <div className="text-[10px] font-semibold tracking-widest text-gray-400 dark:text-slate-500 uppercase">
            Request type
          </div>
          {COLUMNS.map((c, i) => (
            <div
              key={c.key}
              className={`text-center text-xs font-medium text-gray-600 dark:text-slate-300 pb-1 ${
                i === FEEDBACK_DIVIDER_COL ? "border-l border-gray-200 dark:border-slate-700" : ""
              }`}
            >
              {c.label}
            </div>
          ))}
        </div>

        {/* Theme rows */}
        {themes.map((theme, row) => (
          <div
            key={theme.rank}
            className="grid items-stretch gap-1 mb-1"
            style={{ gridTemplateColumns: `minmax(180px,2fr) repeat(${COLUMNS.length}, minmax(64px,1fr))` }}
          >
            <div className="flex items-center gap-2 pr-2 min-w-0">
              <span className="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center text-[10px] font-bold text-indigo-600 dark:text-indigo-400">
                {theme.rank}
              </span>
              <span className="truncate text-sm text-gray-800 dark:text-slate-200" title={theme.theme}>
                {theme.theme}
              </span>
              <span className="flex-shrink-0 text-[10px] text-gray-400 dark:text-slate-500">
                {theme.count}
              </span>
            </div>
            {COLUMNS.map((c, col) => {
              const value = theme.outcome?.[c.key] ?? 0;
              const pct = theme.count > 0 ? Math.round((value / theme.count) * 100) : 0;
              const display = mode === "rate" ? `${pct}%` : `${value}`;
              const alpha = Math.max(value > 0 ? 0.12 : 0, intensity(c, theme));
              const isHover = hover?.row === row && hover?.col === col;
              return (
                <div
                  key={c.key}
                  className={`relative h-9 rounded flex items-center justify-center text-xs font-medium ${
                    col === FEEDBACK_DIVIDER_COL ? "ml-1 border-l border-gray-200 dark:border-slate-700 pl-1" : ""
                  }`}
                  style={{ backgroundColor: `rgba(${c.rgb},${alpha.toFixed(3)})` }}
                  onMouseEnter={() => setHover({ row, col })}
                  onMouseLeave={() => setHover(null)}
                >
                  <span className={value > 0 ? "text-gray-900 dark:text-white" : "text-gray-300 dark:text-slate-600"}>
                    {display}
                  </span>
                  {isHover && value > 0 && (
                    <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 z-10 bg-gray-900 dark:bg-slate-700 text-white text-xs rounded-lg px-2 py-1 whitespace-nowrap shadow-lg pointer-events-none">
                      {value} · {theme.count > 0 ? Math.round((value / theme.count) * 100) : 0}% of “{theme.theme}”
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {/* Example traces for the top themes */}
      <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-gray-400 dark:text-slate-500">
        {themes.slice(0, 3).map((t) =>
          t.trace_ids.length > 0 ? (
            <span key={t.rank}>
              {t.theme}:{" "}
              <Link href={`/traces/${t.trace_ids[0]}`} className="hover:text-indigo-500 hover:underline">
                example trace
              </Link>
            </span>
          ) : null,
        )}
      </div>
    </div>
  );
}
