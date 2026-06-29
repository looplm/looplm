"use client";

import { useState } from "react";
import { ACCENT, STATUS, fmt, statusOf, type Accent, type MetricKind } from "./constants";

export function Info({ text }: { text: string }) {
  // Custom tooltip (not the native `title`, which is slow/unreliable). Positioned with
  // `fixed` so it escapes the metric card's `overflow-hidden` instead of being clipped.
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);

  return (
    <>
      <span
        role="img"
        aria-label={text}
        onMouseEnter={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setPos({ x: r.left + r.width / 2, y: r.top });
        }}
        onMouseLeave={() => setPos(null)}
        className="ml-1 inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-gray-300 dark:border-slate-600 text-gray-400 dark:text-slate-500 text-[9px] font-semibold leading-none cursor-help align-middle hover:border-gray-400 hover:text-gray-600 dark:hover:border-slate-400 dark:hover:text-slate-300"
      >
        i
      </span>
      {pos && (
        <span
          className="fixed z-50 w-60 -translate-x-1/2 -translate-y-full rounded-lg bg-slate-900 dark:bg-slate-800 px-3 py-2 text-[11px] font-normal normal-case leading-snug tracking-normal text-slate-100 shadow-xl ring-1 ring-black/10 pointer-events-none"
          style={{ left: pos.x, top: pos.y - 8 }}
        >
          {text}
        </span>
      )}
    </>
  );
}

export function MetricCard({
  label,
  value,
  target,
  kind,
  hint,
  accent,
  info,
}: {
  label: string;
  value: number | null | undefined;
  target: number | null;
  kind: MetricKind;
  hint: string;
  accent: Accent;
  info: string;
}) {
  const status = statusOf(value, target);
  const barClass = status === "none" ? ACCENT[accent].bar : STATUS[status].bar;
  const valueClass = status === "none" ? ACCENT[accent].text : STATUS[status].text;

  return (
    <div className="relative overflow-hidden rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-3.5">
      <div className={`absolute inset-x-0 top-0 h-0.5 ${barClass}`} />
      <div className="flex items-center text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500">
        {label}
        <Info text={info} />
      </div>
      <div className={`text-3xl font-bold mt-1 tabular-nums ${valueClass}`}>{fmt(kind, value)}</div>
      {target != null ? (
        <div className="flex items-center gap-1 mt-1 text-[11px]">
          <span className="text-gray-400 dark:text-slate-500">Target {fmt(kind, target)}</span>
          {status !== "none" && (
            <span className={STATUS[status].text}>{status === "good" ? "✓" : "✗"}</span>
          )}
        </div>
      ) : (
        <div className="text-[11px] text-gray-400 dark:text-slate-500 mt-1">{hint}</div>
      )}
    </div>
  );
}
