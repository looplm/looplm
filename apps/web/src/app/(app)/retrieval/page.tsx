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

      <section className="mb-10">
        <h2 className="text-xl font-bold mb-1">Targets</h2>
        <p className="text-sm text-gray-500 dark:text-slate-400 mb-4 max-w-3xl">
          Set the pass threshold for each metric (recall@k, nDCG@k, MRR, hit-rate@k, precision@k).
          Cards turn green when a measured value meets its target.
        </p>
        <RetrievalTargetsConfig canEdit={canEdit} />
      </section>

      <RetrievalMetricsPanel onRunSaved={() => setRunsRefresh((n) => n + 1)} />

      <section className="mt-12">
        <h2 className="text-xl font-bold mb-1">Saved runs</h2>
        <p className="text-sm text-gray-500 dark:text-slate-400 mb-4 max-w-3xl">
          Every Human-labels computation is snapshotted here. Annotate runs with their RAG pipeline
          version and index name/version, then select two or more to compare how retrieval quality
          moved as the pipeline and index changed.
        </p>
        <RunHistory refreshKey={runsRefresh} canEdit={canEdit} />
      </section>
    </div>
  );
}
