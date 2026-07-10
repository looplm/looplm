"use client";

/**
 * Cross-run trend of the headline chunk-quality metrics, so a chunker change
 * can be compared against the previous runs at a glance. Data comes from the
 * run summaries' lifted `headline` map; runs are shown oldest to newest.
 */

import { useState } from "react";

import type { ChunkQualityRunSummary } from "@/lib/api-types/chunk-quality";

const METRICS: { key: string; label: string }[] = [
  { key: "score", label: "Health score" },
  { key: "standalone_dependent_pct", label: "Context-dependent %" },
  { key: "boundary_bad_end_pct", label: "End mid-content %" },
  { key: "boundary_bad_start_pct", label: "Start mid-sentence %" },
  { key: "cohesion_high_spread_pct", label: "Multi-topic %" },
  { key: "retrieval_dead_pct", label: "Dead chunks %" },
  { key: "claim_cross_boundary_pct", label: "Cross-boundary claims %" },
];

const MAX_RUNS = 12;

function metricValue(run: ChunkQualityRunSummary, key: string): number | null {
  if (key === "score") return run.score;
  const v = run.headline?.[key];
  return typeof v === "number" ? v : null;
}

export function TrendPanel({ runs }: { runs: ChunkQualityRunSummary[] }) {
  const completed = runs.filter((r) => r.status === "completed").slice(0, MAX_RUNS).reverse();
  const withData = (key: string) => completed.some((r) => metricValue(r, key) !== null);
  const available = METRICS.filter((m) => withData(m.key));
  const [metric, setMetric] = useState(METRICS[0].key);

  if (completed.length < 2 || available.length === 0) return null;
  const active = available.some((m) => m.key === metric) ? metric : available[0].key;
  const values = completed.map((r) => metricValue(r, active));
  const max = Math.max(1, ...values.filter((v): v is number => v !== null));
  // Lower is better for every metric except the health score.
  const goodIsLow = active !== "score";

  return (
    <div className="rounded-xl border border-gray-100 dark:border-slate-800 p-4 mb-5">
      <div className="flex items-center justify-between gap-4 mb-3">
        <p className="text-sm font-semibold">Trend across runs</p>
        <select
          value={active}
          onChange={(e) => setMetric(e.target.value)}
          className="px-2 py-1 rounded border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-xs"
        >
          {available.map((m) => (
            <option key={m.key} value={m.key}>
              {m.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-end gap-2 h-28">
        {completed.map((r, i) => {
          const v = values[i];
          const pct = v === null ? 0 : (v / max) * 100;
          const isLatest = i === completed.length - 1;
          const tone =
            v === null
              ? "bg-gray-200 dark:bg-slate-800"
              : goodIsLow === (v / max > 0.66)
                ? "bg-amber-500"
                : "bg-indigo-500";
          return (
            <div key={r.id} className="flex-1 flex flex-col items-center gap-1 min-w-0">
              <span className="text-[10px] text-gray-500 dark:text-slate-400">
                {v === null ? "—" : Math.round(v * 10) / 10}
              </span>
              <div className="w-full flex items-end h-16">
                <div
                  className={`w-full rounded-t ${tone} ${isLatest ? "" : "opacity-60"}`}
                  style={{ height: `${Math.max(2, pct)}%` }}
                  title={new Date(r.created_at).toLocaleString()}
                />
              </div>
              <span className="text-[10px] text-gray-400 dark:text-slate-500 truncate max-w-full">
                {new Date(r.created_at).toLocaleDateString()}
              </span>
            </div>
          );
        })}
      </div>
      <p className="text-[11px] text-gray-400 dark:text-slate-500 mt-2">
        Oldest to newest. Only completed runs are shown; a run must include a pass for its metric
        to appear.
      </p>
    </div>
  );
}
