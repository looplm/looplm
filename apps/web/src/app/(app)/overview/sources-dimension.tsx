"use client";

import { useState } from "react";
import { SERIES } from "./overview-constants";
import { formatNumber } from "./overview-format";

export interface DimensionRow {
  key: string;
  label: string;
  count: number;
  sublabel?: string;
  /** Rendered muted, for rows like "(not set)". */
  muted?: boolean;
}

export interface SourcesDimensionProps {
  rows: DimensionRow[];
  unit: string;
  /** Denominator for the bars. Defaults to the largest row. */
  total?: number;
  /** Rows beyond this collapse behind a "show more" toggle. */
  topN?: number;
  barClassName?: string;
  emptyLabel?: string;
}

/** Ranked horizontal bar list, reused for every sources dimension. */
export function SourcesDimension({
  rows,
  unit,
  total,
  topN = 8,
  barClassName = SERIES.bar,
  emptyLabel = "Nothing to show yet",
}: SourcesDimensionProps) {
  const [expanded, setExpanded] = useState(false);

  if (rows.length === 0) {
    return <p className="text-sm text-gray-500 dark:text-slate-400">{emptyLabel}</p>;
  }

  const sorted = [...rows].sort((a, b) => b.count - a.count);
  const denominator = total ?? Math.max(...sorted.map((r) => r.count), 1);
  const visible = expanded ? sorted : sorted.slice(0, topN);
  const hidden = sorted.length - visible.length;

  return (
    <div>
      <ul className="space-y-1.5">
        {visible.map((row) => (
          <li key={row.key} className="flex items-center gap-3 text-xs">
            <span
              className={`w-32 shrink-0 truncate ${
                row.muted
                  ? "text-gray-400 dark:text-slate-500"
                  : "text-gray-700 dark:text-slate-200"
              }`}
              title={row.sublabel ? `${row.label} (${row.sublabel})` : row.label}
            >
              {row.label}
            </span>
            <span className="flex-1 h-2 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
              <span
                className={`block h-full rounded-full ${barClassName}`}
                style={{ width: `${Math.max((row.count / denominator) * 100, 1)}%` }}
              />
            </span>
            <span className="w-16 text-right tabular-nums text-gray-600 dark:text-slate-300">
              {formatNumber(row.count)}
            </span>
          </li>
        ))}
      </ul>
      {hidden > 0 || expanded ? (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
        >
          {expanded ? "Show fewer" : `Show ${hidden} more`}
        </button>
      ) : null}
      <p className="mt-2 text-[10px] text-gray-400 dark:text-slate-500">
        {formatNumber(sorted.reduce((sum, r) => sum + r.count, 0))} {unit} total
      </p>
    </div>
  );
}
