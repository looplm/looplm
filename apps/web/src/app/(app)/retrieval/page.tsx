"use client";

import { useState } from "react";
import { usePermissions } from "@/components/permissions-context";
import { RetrievalTargetsConfig } from "@/components/retrieval/targets-config";
import { RunMetadataEditor } from "@/components/retrieval/run-metadata-editor";
import RetrievalMetricsPanel from "@/components/retrieval-metrics-panel";
import { RunHistory } from "@/components/retrieval/run-history";
import { RetrievalReadinessBanner } from "@/components/retrieval/readiness-banner";
import type { RetrievalRunRecord } from "@/lib/api";

export default function RetrievalPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("pipeline");
  // Bumped whenever the panel auto-saves or edits a run, so the history list refetches.
  const [runsRefresh, setRunsRefresh] = useState(0);
  // The saved run shown in the metrics panel. Defaults to the latest (set by RunHistory once loaded)
  // and follows clicks in the history list.
  const [viewRunId, setViewRunId] = useState<string | null>(null);
  // The run currently displayed in the panel — annotated in the editor below the panel.
  const [displayedRun, setDisplayedRun] = useState<RetrievalRunRecord | null>(null);

  return (
    <div>
      <h1 className="text-3xl font-bold mb-1">Retrieval</h1>
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-6 max-w-3xl">
        Define your retrieval-quality targets and see how the pipeline measures up. Outcomes are
        computed against your expected URLs (per eval run) or human/AI chunk labels (across the
        datasets you pick), with a per-stage breakdown for sparse, dense, RRF, reranking and the
        agentic path.
      </p>

      <RetrievalReadinessBanner />

      <RetrievalMetricsPanel
        onRunSaved={() => setRunsRefresh((n) => n + 1)}
        viewRunId={viewRunId}
        onViewRunChange={setViewRunId}
        onDisplayedRunChange={setDisplayedRun}
      />

      <details className="mt-10 group">
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

      {displayedRun && (
        <div className="mt-10">
          <RunMetadataEditor
            run={displayedRun}
            canEdit={canEdit}
            onSaved={(u) => {
              setDisplayedRun(u);
              setRunsRefresh((n) => n + 1);
            }}
          />
        </div>
      )}

      <details className="mt-10 group">
        <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
          <span className="text-gray-400 transition-transform group-open:rotate-90">▸</span>
          <h2 className="text-xl font-bold">Saved runs</h2>
        </summary>
        <p className="text-sm text-gray-500 dark:text-slate-400 mt-2 mb-4 max-w-3xl">
          Every Human-labels computation is snapshotted here. Annotate runs with their RAG pipeline
          version and index name/version, then select two or more to compare how retrieval quality
          moved as the pipeline and index changed.
        </p>
        <RunHistory
          refreshKey={runsRefresh}
          canEdit={canEdit}
          selectedRunId={viewRunId}
          onSelectRun={setViewRunId}
        />
      </details>
    </div>
  );
}
