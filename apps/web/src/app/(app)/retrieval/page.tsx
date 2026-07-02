"use client";

import { useState } from "react";
import { usePermissions } from "@/components/permissions-context";
import { RetrievalTargetsConfig } from "@/components/retrieval/targets-config";
import RetrievalMetricsPanel from "@/components/retrieval-metrics-panel";
import { RunHistory } from "@/components/retrieval/run-history";

export default function RetrievalPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("pipeline");
  // Bumped whenever the panel auto-saves or edits a run, so the history list refetches.
  const [runsRefresh, setRunsRefresh] = useState(0);

  return (
    <div>
      <h1 className="text-3xl font-bold mb-1">Retrieval</h1>
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-6 max-w-3xl">
        Define your retrieval-quality targets and see how the pipeline measures up. Outcomes are
        computed against your expected URLs (per eval run) or human/AI chunk labels (across the
        datasets you pick), with a per-stage breakdown for sparse, dense, RRF, reranking and the
        agentic path.
      </p>

      <details className="mb-10 group">
        <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
          <span className="text-gray-400 transition-transform group-open:rotate-90">▸</span>
          <h2 className="text-xl font-bold">Targets</h2>
          <span className="text-sm text-gray-400 dark:text-slate-500">(pass thresholds)</span>
        </summary>
        <p className="text-sm text-gray-500 dark:text-slate-400 mt-2 mb-4 max-w-3xl">
          Set the pass threshold for each metric (recall@k, nDCG@k, MRR, hit-rate@k, precision@k).
          Cards turn green when a measured value meets its target.
        </p>
        <RetrievalTargetsConfig canEdit={canEdit} />
      </details>

      <RetrievalMetricsPanel onRunSaved={() => setRunsRefresh((n) => n + 1)} />

      <details className="mt-12 group">
        <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
          <span className="text-gray-400 transition-transform group-open:rotate-90">▸</span>
          <h2 className="text-xl font-bold">Saved runs</h2>
        </summary>
        <p className="text-sm text-gray-500 dark:text-slate-400 mt-2 mb-4 max-w-3xl">
          Every Human-labels computation is snapshotted here. Annotate runs with their RAG pipeline
          version and index name/version, then select two or more to compare how retrieval quality
          moved as the pipeline and index changed.
        </p>
        <RunHistory refreshKey={runsRefresh} canEdit={canEdit} />
      </details>
    </div>
  );
}
