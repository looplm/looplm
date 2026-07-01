"use client";

import { useState } from "react";
import { toast } from "sonner";
import { getLabelingView, aiJudgeCase } from "@/lib/api";
import { runBounded } from "@/lib/run-bounded";

// One-click AI judge across whole datasets: enumerate every case in the target datasets, then run
// the per-case judge over all of them with bounded concurrency. Each case is an independent request
// (own pool, own transaction), so this parallelizes safely and reports live progress. Reuses the
// judge endpoint that plans agentic queries if missing and grades full chunk text, so the AI-gold
// labels it writes match exactly what the per-case labeler produces.
//
// The browser caps concurrent requests per origin (~6), which is the effective parallelism here.
const CONCURRENCY = 6;

export function JudgeAllButton({
  datasets,
  selectedIds,
  onDone,
}: {
  datasets: { id: string; name: string }[];
  // The datasets currently in scope on the panel; empty means "all datasets" (the metrics default
  // is most-recent, but judging is explicit about covering everything so the AI gold is complete).
  selectedIds: string[];
  // Called after judging finishes so the caller can recompute metrics against the new AI labels.
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);

  const targetIds = selectedIds.length > 0 ? selectedIds : datasets.map((d) => d.id);
  const label =
    selectedIds.length > 0
      ? `Judge ${selectedIds.length} dataset${selectedIds.length === 1 ? "" : "s"}`
      : `Judge all ${datasets.length} dataset${datasets.length === 1 ? "" : "s"}`;

  const run = async () => {
    if (busy || targetIds.length === 0) return;
    setBusy(true);
    setProgress({ done: 0, total: 0 });
    try {
      // Enumerate cases per dataset, deduped by test_id (a case labeled in one dataset carries its
      // labels everywhere), keeping the dataset it first appeared in for the judge's pool context.
      const seen = new Set<string>();
      const cases: { testId: string; datasetId: string }[] = [];
      const views = await Promise.all(
        targetIds.map((id) => getLabelingView(id).catch(() => null)),
      );
      views.forEach((v, i) => {
        for (const c of v?.cases ?? []) {
          if (!seen.has(c.test_id)) {
            seen.add(c.test_id);
            cases.push({ testId: c.test_id, datasetId: targetIds[i] });
          }
        }
      });

      if (cases.length === 0) {
        toast.info("No cases to judge in the selected datasets.");
        return;
      }

      setProgress({ done: 0, total: cases.length });
      let judged = 0;
      await runBounded(
        cases,
        CONCURRENCY,
        (c) => aiJudgeCase(c.testId, { datasetId: c.datasetId }).then(() => void judged++),
        (done) => setProgress({ done, total: cases.length }),
      );
      toast.success(`AI judged ${judged} of ${cases.length} question${cases.length === 1 ? "" : "s"}`);
      onDone();
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };

  return (
    <div className="flex items-center gap-2">
      {busy && progress && (
        <span className="text-[11px] text-gray-400 dark:text-slate-500 tabular-nums">
          Judging {progress.done}/{progress.total}…
        </span>
      )}
      <button
        onClick={run}
        disabled={busy || targetIds.length === 0}
        title="Run the AI judge over every question's chunks across these datasets (default rubric). Populates the AI-judge gold."
        className="inline-flex items-center gap-1 text-sm rounded-lg border border-violet-300 dark:border-violet-700/60 text-violet-600 dark:text-violet-300 px-3 py-1.5 hover:border-violet-400 disabled:opacity-40"
      >
        <span aria-hidden className={busy ? "animate-pulse" : ""}>✦</span>
        {busy ? "Judging…" : label}
      </button>
    </div>
  );
}
