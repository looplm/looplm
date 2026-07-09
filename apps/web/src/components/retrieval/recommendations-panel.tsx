"use client";

import { useState } from "react";
import Link from "next/link";
import type { ByStageMetricsResponse, RetrievalRunMetrics, RetrievalTargets } from "@/lib/api";
import {
  buildRecommendations,
  stageLabel,
  type Recommendation,
  type Severity,
} from "./recommendations";

// The "What to improve" panel: the rule engine's findings for the computed metrics, most-severe
// first, each attributing the problem to a pipeline step with a concrete lever. Presentational —
// the parent owns fetching and the @k selection.

const SEV: Record<Severity, { dot: string; label: string; badge: string }> = {
  high: { dot: "bg-red-500", label: "Fix", badge: "bg-red-500/10 text-red-600 dark:text-red-300" },
  medium: {
    dot: "bg-amber-500",
    label: "Improve",
    badge: "bg-amber-500/10 text-amber-600 dark:text-amber-300",
  },
  low: { dot: "bg-sky-500", label: "Consider", badge: "bg-sky-500/10 text-sky-600 dark:text-sky-300" },
  good: {
    dot: "bg-emerald-500",
    label: "Good",
    badge: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  },
};

// Actions scroll to the relevant section further down the page (added ids there) or link out.
function scrollToId(id: string) {
  if (typeof document === "undefined") return;
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function ActionControl({ action }: { action: NonNullable<Recommendation["action"]> }) {
  const cls =
    "text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300";
  if (action.kind === "labeling") {
    return (
      <Link href="/labeling" className={cls}>
        {action.label} ↗
      </Link>
    );
  }
  const targetId = action.kind === "diagnose" ? "retrieval-per-case" : "retrieval-by-stage";
  return (
    <button type="button" onClick={() => scrollToId(targetId)} className={cls}>
      {action.label} ↓
    </button>
  );
}

function RecRow({ rec }: { rec: Recommendation }) {
  const sev = SEV[rec.severity];
  return (
    <div className="flex gap-3 py-3">
      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${sev.dot}`} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-gray-800 dark:text-slate-100">{rec.title}</span>
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${sev.badge}`}>
            {sev.label}
          </span>
          <span className="rounded-full bg-gray-100 dark:bg-slate-800 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-500 dark:text-slate-400">
            {stageLabel(rec.stage)}
          </span>
        </div>
        <p className="mt-1 text-sm leading-snug text-gray-600 dark:text-slate-400">{rec.detail}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
          {rec.basis.map((b) => (
            <span
              key={b}
              className="rounded bg-gray-50 dark:bg-slate-800/60 px-1.5 py-0.5 font-mono text-[10px] text-gray-400 dark:text-slate-500"
            >
              {b}
            </span>
          ))}
          {rec.action && <ActionControl action={rec.action} />}
        </div>
      </div>
    </div>
  );
}

export function RecommendationsPanel({
  overall,
  byStage,
  targets,
  k,
  source,
  retriever,
}: {
  overall: RetrievalRunMetrics | null;
  byStage: ByStageMetricsResponse | null;
  targets: RetrievalTargets | null;
  k: number;
  source: "urls" | "labels";
  // The selected retriever, so the findings reason from the ranking on screen.
  retriever: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const recs = buildRecommendations({ overall, byStage, targets, k, source, retriever });
  if (recs.length === 0) return null;

  const TOP = 5;
  const shown = expanded ? recs : recs.slice(0, TOP);
  const hidden = recs.length - shown.length;

  return (
    <div className="mb-4 rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-3">
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500">
        What to improve
        <span className="text-gray-300 dark:text-slate-600">·</span>
        <span className="normal-case tracking-normal">at @{k}</span>
      </div>
      <div className="mt-1 divide-y divide-gray-100 dark:divide-slate-800">
        {shown.map((rec) => (
          <RecRow key={rec.id} rec={rec} />
        ))}
      </div>
      {hidden > 0 && !expanded && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-2 text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300"
        >
          Show {hidden} more
        </button>
      )}
    </div>
  );
}
