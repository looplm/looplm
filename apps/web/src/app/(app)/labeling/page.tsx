"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  getLabelingView,
  getLabelingPool,
  getIndexProviders,
  aiJudgeCase,
  type LabelingRunResponse,
} from "@/lib/api";
import { usePermissions } from "@/components/permissions-context";
import { AgreementPanel } from "@/components/labeling/agreement-panel";
import { LabelingControls } from "@/components/labeling/labeling-controls";
import { JudgeAllButton } from "@/components/retrieval/judge-all-button";
import { runBounded } from "@/lib/run-bounded";

const SLICE_BADGE: Record<string, string> = {
  safety: "bg-red-500/10 text-red-600 dark:text-red-300 border-red-500/30",
  adversarial: "bg-orange-500/10 text-orange-600 dark:text-orange-300 border-orange-500/30",
  broad: "bg-slate-500/10 text-slate-600 dark:text-slate-300 border-slate-500/20",
};

export default function LabelingIndexPage() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("labeling");

  const [view, setView] = useState<LabelingRunResponse | null>(null);
  // Undefined until the first view resolves (backend picks the most-recent dataset).
  const [datasetId, setDatasetId] = useState<string | undefined>(undefined);
  const [tab, setTab] = useState<"in_progress" | "complete">("in_progress");
  const [indexConnected, setIndexConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState<"recompute" | "judge" | null>(null);
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null);

  useEffect(() => {
    getIndexProviders()
      .then((res) => setIndexConnected(res.data.length > 0))
      .catch(() => setIndexConnected(false));
  }, []);

  const load = useCallback((dsId?: string) => {
    setLoading(true);
    setError(null);
    return getLabelingView(dsId)
      .then((v) => {
        setView(v);
        setDatasetId(v.dataset_id ?? undefined);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load(datasetId);
  }, [datasetId, load]);

  const recomputeAll = useCallback(async () => {
    if (!view) return;
    const ids = view.cases.map((c) => c.test_id);
    if (ids.length === 0) return;
    setBulkBusy("recompute");
    setBulkProgress({ done: 0, total: ids.length });
    try {
      await runBounded(
        ids,
        4,
        (id) => getLabelingPool(id, { datasetId: view.dataset_id ?? undefined, refresh: true }).then(() => {}),
        (done) => setBulkProgress({ done, total: ids.length }),
      );
      toast.success(`Recomputed ${ids.length} pool${ids.length === 1 ? "" : "s"}`);
    } finally {
      setBulkBusy(null);
      setBulkProgress(null);
    }
  }, [view]);

  const aiJudgeAll = useCallback(async () => {
    if (!view) return;
    const ids = view.cases.map((c) => c.test_id);
    if (ids.length === 0) return;
    setBulkBusy("judge");
    setBulkProgress({ done: 0, total: ids.length });
    const judged = new Set<string>();
    try {
      await runBounded(
        ids,
        3,
        (id) =>
          aiJudgeCase(id, { datasetId: view.dataset_id ?? undefined }).then(() => {
            judged.add(id);
          }),
        (done) => setBulkProgress({ done, total: ids.length }),
      );
      // Reflect the AI annotator now present on judged cases.
      setView((prev) =>
        prev
          ? {
              ...prev,
              cases: prev.cases.map((c) =>
                judged.has(c.test_id) && !c.labelers.includes("AI")
                  ? { ...c, labelers: [...c.labelers, "AI"] }
                  : c,
              ),
            }
          : prev,
      );
      toast.success(`AI judged ${judged.size} question${judged.size === 1 ? "" : "s"}`);
    } finally {
      setBulkBusy(null);
      setBulkProgress(null);
    }
  }, [view]);

  const datasets = view?.datasets ?? [];
  const completeCount = useMemo(() => (view?.cases ?? []).filter((c) => c.complete).length, [view]);

  const caseHref = (testId: string) =>
    `/labeling/${encodeURIComponent(testId)}${datasetId ? `?dataset=${encodeURIComponent(datasetId)}` : ""}`;

  return (
    <div>
      <div className="flex items-center justify-between gap-4 mb-1">
        <h1 className="text-3xl font-bold">Labeling</h1>
        {datasets.length > 0 && (
          <div className="flex items-center gap-2">
            {canEdit && indexConnected && (
              <JudgeAllButton datasets={datasets} selectedIds={[]} onDone={() => load(datasetId)} />
            )}
            <select
              value={datasetId ?? ""}
              onChange={(e) => setDatasetId(e.target.value || undefined)}
              className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 text-sm"
              title="Dataset to label"
            >
              {datasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} ({d.test_count})
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-5 max-w-3xl">
        Pick a question to judge the chunks your index retrieves for it. Grade each one 0
        (irrelevant), 1 (marginally relevant), 2 (relevant), or 3 (highly relevant); these labels
        are the ground truth for the chunk-level precision, recall and nDCG on the Pipeline page
        (any grade ≥ 1 counts as relevant; nDCG weights by grade).
      </p>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      )}

      {indexConnected === false && !loading && (
        <div className="mb-4 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-amber-600 dark:text-amber-400 text-sm">
          No index provider is connected. Connect one in Settings → Integrations so candidate chunks
          can be pooled from the index for each query.
        </div>
      )}

      {loading ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          Loading test cases...
        </div>
      ) : datasets.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          No datasets yet. Create a dataset (Datasets) with the queries you want to label, then come
          back here.
        </div>
      ) : !view || !view.available ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          This dataset has no test cases. Add some in Datasets, then come back to label.
        </div>
      ) : (
        <>
          <LabelingControls
            complete={completeCount}
            total={view.cases.length}
            canEdit={canEdit}
            indexConnected={indexConnected}
            bulkBusy={bulkBusy}
            bulkProgress={bulkProgress}
            onRecomputeAll={recomputeAll}
            onAiJudgeAll={aiJudgeAll}
          />

          <AgreementPanel canEdit={canEdit} />

          {(() => {
            const inProgress = view.cases.filter((c) => !c.complete);
            const complete = view.cases.filter((c) => c.complete);
            const active = tab === "in_progress" ? inProgress : complete;
            const tabs = [
              { key: "in_progress" as const, label: "In progress", count: inProgress.length },
              { key: "complete" as const, label: "Complete", count: complete.length },
            ];
            return (
              <>
                <div className="flex items-center gap-1 mb-4 border-b border-gray-100 dark:border-slate-800">
                  {tabs.map((t) => (
                    <button
                      key={t.key}
                      onClick={() => setTab(t.key)}
                      className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                        tab === t.key
                          ? "border-indigo-500 text-gray-900 dark:text-white"
                          : "border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
                      }`}
                    >
                      {t.label}
                      <span className="ml-1.5 text-xs text-gray-400 dark:text-slate-500">{t.count}</span>
                    </button>
                  ))}
                </div>

                {active.length > 0 ? (
                  <div className="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden divide-y divide-gray-100 dark:divide-slate-800">
                    {active.map((c) => (
                      <Link
                        key={c.test_id}
                        href={caseHref(c.test_id)}
                        className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors"
                      >
                        <span className="min-w-0 flex-1 text-[14px] text-gray-900 dark:text-white truncate">
                          {c.input || c.test_id}
                        </span>
                        {c.labelers.length > 0 && (
                          <span
                            className="hidden md:inline text-[11px] italic text-gray-400 dark:text-slate-500 truncate max-w-[160px]"
                            title={`Labeled by ${c.labelers.join(", ")}`}
                          >
                            by {c.labelers.join(", ")}
                          </span>
                        )}
                        <span className="shrink-0 text-[11px] text-gray-400 dark:text-slate-500 tabular-nums">
                          {c.labeled_count} labeled · {c.relevant_count} relevant
                        </span>
                        <span
                          className={`shrink-0 rounded-lg border px-2 py-0.5 text-[11px] font-medium capitalize ${
                            SLICE_BADGE[c.slice ?? "broad"]
                          }`}
                        >
                          {c.slice ?? "broad"}
                        </span>
                        {c.complete && (
                          <span className="shrink-0 rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 px-2 py-0.5 text-[11px] font-medium">
                            ✓ Complete
                          </span>
                        )}
                        <span aria-hidden className="shrink-0 text-gray-300 dark:text-slate-600">
                          →
                        </span>
                      </Link>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400 dark:text-slate-500">
                    {tab === "in_progress"
                      ? "All cases are marked complete."
                      : "No cases marked complete yet."}
                  </p>
                )}
              </>
            );
          })()}
        </>
      )}
    </div>
  );
}
