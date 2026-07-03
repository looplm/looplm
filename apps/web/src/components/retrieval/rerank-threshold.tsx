"use client";

import { useMemo, useState } from "react";
import type { RerankThresholdPoint } from "@/lib/api";
import { pct } from "./constants";
import { Info } from "./metric-card";

const INFO =
  "The agentic pool feeds the LLM the chunks whose Azure rerankerScore (0-4) clears this cutoff, " +
  "instead of a fixed top-k. Drag to trade precision (less noise) against recall (more coverage) " +
  "and see how many chunks per query you'd send. Pick where precision meets your target while " +
  "recall is still acceptable.";

// Plot geometry (viewBox units); padding leaves room for the axis labels.
const PAD = 6;
const span = (100 - 2 * PAD);

export function RerankThreshold({
  sweep,
  precisionTarget,
}: {
  sweep: RerankThresholdPoint[];
  precisionTarget: number | null;
}) {
  const tMin = sweep[0].threshold;
  const tMax = sweep[sweep.length - 1].threshold;
  const range = Math.max(0.0001, tMax - tMin);

  // Default to the cheapest cutoff that meets the precision target (most recall while still on
  // target), else the lowest threshold — a sensible starting point, not a hidden decision.
  const defaultT = useMemo(() => {
    if (precisionTarget != null) {
      const hit = sweep.find((p) => p.precision != null && p.precision >= precisionTarget);
      if (hit) return hit.threshold;
    }
    return tMin;
  }, [sweep, precisionTarget, tMin]);
  const [t, setT] = useState(defaultT);

  // Nearest computed point to the slider value drives the readout.
  const point = useMemo(
    () => sweep.reduce((a, b) => (Math.abs(b.threshold - t) < Math.abs(a.threshold - t) ? b : a)),
    [sweep, t],
  );

  const x = (thr: number) => PAD + ((thr - tMin) / range) * span;
  const y = (v: number) => 100 - PAD - Math.min(1, Math.max(0, v)) * span;
  const line = (get: (p: RerankThresholdPoint) => number | null | undefined) =>
    sweep
      .map((p) => ({ p, v: get(p) }))
      .filter((d): d is { p: RerankThresholdPoint; v: number } => typeof d.v === "number")
      .map((d) => `${x(d.p.threshold).toFixed(2)},${y(d.v).toFixed(2)}`)
      .join(" ");

  const precisionOk = precisionTarget == null || (point.precision ?? 0) >= precisionTarget;

  return (
    <div className="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 mb-6">
      <div className="flex items-center text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-3">
        Score threshold
        <Info text={INFO} />
      </div>

      <div className="grid gap-5 md:grid-cols-[1fr_260px] items-center">
        {/* Precision (indigo) vs recall (amber) as the cutoff sweeps, with a marker at the pick. */}
        <svg viewBox="0 0 100 60" preserveAspectRatio="none" className="w-full h-28">
          {[0.25, 0.5, 0.75, 1].map((g) => (
            <line
              key={g}
              x1={PAD}
              x2={100 - PAD}
              y1={(100 - PAD - g * span) * 0.6}
              y2={(100 - PAD - g * span) * 0.6}
              className="stroke-gray-100 dark:stroke-slate-800"
              strokeWidth={0.4}
              strokeDasharray="1 1"
            />
          ))}
          {precisionTarget != null && (
            <line
              x1={PAD}
              x2={100 - PAD}
              y1={y(precisionTarget) * 0.6}
              y2={y(precisionTarget) * 0.6}
              className="stroke-emerald-500/70"
              strokeWidth={0.6}
              strokeDasharray="2 1.5"
            />
          )}
          {/* Vertical marker at the selected threshold. */}
          <line
            x1={x(point.threshold)}
            x2={x(point.threshold)}
            y1={PAD * 0.6}
            y2={(100 - PAD) * 0.6}
            className="stroke-gray-300 dark:stroke-slate-600"
            strokeWidth={0.5}
          />
          <g transform="scale(1,0.6)">
            <polyline points={line((p) => p.recall)} fill="none" className="stroke-amber-500" strokeWidth={0.9} vectorEffect="non-scaling-stroke" />
            <polyline points={line((p) => p.precision)} fill="none" className="stroke-indigo-500" strokeWidth={0.9} vectorEffect="non-scaling-stroke" />
          </g>
        </svg>

        <div>
          <div className="flex items-baseline justify-between mb-2">
            <span className="text-[11px] uppercase tracking-wide text-gray-400 dark:text-slate-500">Cutoff</span>
            <span className="font-mono text-lg font-semibold tabular-nums text-gray-800 dark:text-slate-100">
              {point.threshold.toFixed(1)}
            </span>
          </div>
          <input
            type="range"
            min={tMin}
            max={tMax}
            step={0.1}
            value={t}
            onChange={(e) => setT(Number(e.target.value))}
            className="w-full accent-indigo-600"
            aria-label="rerankerScore cutoff"
          />
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            <Stat label="Precision" value={pct(point.precision)} accent={precisionOk ? "text-indigo-600 dark:text-indigo-400" : "text-amber-600 dark:text-amber-400"} />
            <Stat label="Recall" value={pct(point.recall)} accent="text-amber-600 dark:text-amber-400" />
            <Stat label="Chunks/q" value={point.avg_retrieved.toFixed(1)} accent="text-gray-700 dark:text-slate-200" />
          </div>
          {/* Reserve two lines so the row height (and the chart's vertical position) stays put
              whether or not the "Below your precision target." suffix wraps to a second line. */}
          <p className="mt-2 min-h-8 text-[11px] leading-4 text-gray-400 dark:text-slate-500">
            Feed chunks scoring ≥ {point.threshold.toFixed(1)} to the model.
            {precisionTarget != null && !precisionOk ? " Below your precision target." : ""}
          </p>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div>
      <div className={`font-mono text-base font-semibold tabular-nums ${accent}`}>{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-gray-400 dark:text-slate-500">{label}</div>
    </div>
  );
}
