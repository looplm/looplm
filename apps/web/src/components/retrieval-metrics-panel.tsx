"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  createRetrievalRun,
  getDatasets,
  getEvalRuns,
  getRetrievalByStageMetrics,
  getRetrievalMetrics,
  getRetrievalTargets,
  pollRetrievalCompute,
  startRetrievalCompute,
  type ByStageMetricsResponse,
  type EvalRunListItem,
  type RetrievalRunMetrics,
  type RetrievalRunRecord,
  type RetrievalTargets,
} from "@/lib/api";
import { usePermissions } from "@/components/permissions-context";
import { EXPLAIN, METRICS, statusOf, type MetricDef } from "@/components/retrieval/constants";
import { Info } from "@/components/retrieval/metric-card";
import { OverallResults } from "@/components/retrieval/overall-results";
import { ByStageComparison } from "@/components/retrieval/by-stage-table";
import { DatasetMultiSelect } from "@/components/retrieval/dataset-multiselect";
import { KSelector } from "@/components/retrieval/k-selector";
import { ErrorNotice } from "@/components/error-notice";
import { ComputedAt } from "@/components/retrieval/computed-at";
import { RunMetadataEditor } from "@/components/retrieval/run-metadata-editor";

type Source = "urls" | "labels";
type GoldSource = "human" | "ai" | "both";

// The settings the user is editing. Computation only runs against the *applied* copy (below).
// The labels path always computes and shows both the Overall and By-stage views together.
type Draft = {
  source: Source;
  goldSource: GoldSource;
  datasetIds: string[];
  runId: string | null;
};
// A snapshot of Draft that has been sent to compute, plus a nonce to retrigger the fetch on
// Recompute (same settings, forced refresh) and a refresh flag.
type Applied = Draft & { refresh: boolean; nonce: number };

const sameSettings = (a: Draft, b: Draft): boolean =>
  a.source === b.source &&
  a.goldSource === b.goldSource &&
  a.runId === b.runId &&
  a.datasetIds.length === b.datasetIds.length &&
  a.datasetIds.every((id) => b.datasetIds.includes(id));

export default function RetrievalMetricsPanel({ onRunSaved }: { onRunSaved?: () => void } = {}) {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("pipeline");

  const [runs, setRuns] = useState<EvalRunListItem[]>([]);
  const [datasets, setDatasets] = useState<{ id: string; name: string }[]>([]);
  const [targets, setTargets] = useState<RetrievalTargets | null>(null);

  const [draft, setDraft] = useState<Draft>({
    source: "labels",
    goldSource: "human",
    datasetIds: [],
    runId: null,
  });
  const setDraftField = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  // Null until the user presses Compute the first time — nothing is computed on load.
  const [applied, setApplied] = useState<Applied | null>(null);

  const [overall, setOverall] = useState<RetrievalRunMetrics | null>(null);
  const [byStage, setByStage] = useState<ByStageMetricsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // By-stage runs as its own (slower) job so the Overall numbers render as soon as they're ready.
  const [byStageLoading, setByStageLoading] = useState(false);
  const [byStageError, setByStageError] = useState<unknown>(null);
  // Display-only cutoff selection — never part of Draft/Applied, so changing it doesn't recompute.
  const [selectedK, setSelectedK] = useState<number | null>(null);
  // The run auto-snapshotted from the current Overall compute, for inline metadata annotation.
  const [savedRun, setSavedRun] = useState<RetrievalRunRecord | null>(null);
  const savedNonceRef = useRef<number | null>(null);
  // Keep the latest onRunSaved without making it an effect dependency (would re-run on each render).
  const onRunSavedRef = useRef(onRunSaved);
  onRunSavedRef.current = onRunSaved;

  useEffect(() => {
    getEvalRuns({ limit: "50" })
      .then((res) => {
        setRuns(res.data);
        // Seed the run picker so the URLs path has a concrete run to compute.
        setDraft((d) => (d.runId ? d : { ...d, runId: res.data[0]?.id ?? null }));
      })
      .catch(() => setRuns([]));
    getDatasets({ per_page: "100" })
      .then((res) => {
        const ds = res.data.map((d) => ({ id: d.id, name: d.name }));
        setDatasets(ds);
        // Default to all datasets selected — a sensible starting point the user can trim.
        setDraft((d) => (d.datasetIds.length ? d : { ...d, datasetIds: ds.map((x) => x.id) }));
      })
      .catch(() => setDatasets([]));
    getRetrievalTargets()
      .then(setTargets)
      .catch(() => setTargets(null));
  }, []);

  // Fetch only when the applied snapshot changes (Compute / Recompute) — never on draft edits.
  // Labels path computes BOTH views as two independent detached jobs, so the fast Overall numbers
  // render without waiting on the slower by-stage pool. Each compute runs server-side and is polled
  // (short HTTP calls), so a reload/proxy timeout can't reset the socket mid-flight; a failed job
  // carries the server error + traceback (debug), surfaced via ErrorNotice.
  useEffect(() => {
    if (!applied) return;
    const controller = new AbortController();
    const signal = controller.signal;
    setError(null);
    setSavedRun(null);

    // Overall (labels: detached job → warm-cache read; urls: direct stored-aggregate read).
    const runOverall = async (): Promise<RetrievalRunMetrics | null> => {
      if (applied.source !== "labels") {
        const m = await getRetrievalMetrics(
          { runId: applied.runId ?? undefined, source: "urls", refresh: applied.refresh },
          signal,
        );
        if (signal.aborted) return null;
        setOverall(m);
        if (!applied.runId && m.run_id) setDraftField("runId", m.run_id);
        return m;
      }
      const job = await startRetrievalCompute(
        { dataset_ids: applied.datasetIds, gold_source: applied.goldSource, view: "overall", refresh: applied.refresh },
        signal,
      );
      await pollRetrievalCompute(job.id, signal);
      if (signal.aborted) return null;
      const m = await getRetrievalMetrics(
        { datasetIds: applied.datasetIds, source: "labels", goldSource: applied.goldSource, refresh: false },
        signal,
      );
      if (!signal.aborted) setOverall(m);
      return m;
    };

    const runByStage = async () => {
      const job = await startRetrievalCompute(
        { dataset_ids: applied.datasetIds, gold_source: applied.goldSource, view: "byStage", refresh: applied.refresh },
        signal,
      );
      await pollRetrievalCompute(job.id, signal);
      if (signal.aborted) return;
      const d = await getRetrievalByStageMetrics(
        { datasetIds: applied.datasetIds, goldSource: applied.goldSource, refresh: false },
        signal,
      );
      if (!signal.aborted) setByStage(d);
    };

    // Snapshot into durable history once both views are computed, so the saved run captures the
    // by-stage breakdown too (server reads it from the warm cache). Best-effort.
    const snapshot = async (m: RetrievalRunMetrics | null) => {
      if (!m?.available || savedNonceRef.current === applied.nonce) return;
      savedNonceRef.current = applied.nonce;
      try {
        const rec = await createRetrievalRun(
          { dataset_ids: applied.datasetIds, gold_source: applied.goldSource },
          signal,
        );
        if (!signal.aborted) {
          setSavedRun(rec);
          onRunSavedRef.current?.();
        }
      } catch {
        /* history snapshot is best-effort; the metrics still render */
      }
    };

    setLoading(true);
    const overallP = runOverall()
      .catch((e) => {
        if (!signal.aborted && e?.name !== "AbortError") setError(e);
        return null;
      })
      .finally(() => {
        if (!signal.aborted) setLoading(false);
      });

    if (applied.source === "labels") {
      setByStageError(null);
      setByStageLoading(true);
      const byStageP = runByStage()
        .catch((e) => {
          if (!signal.aborted && e?.name !== "AbortError") setByStageError(e);
        })
        .finally(() => {
          if (!signal.aborted) setByStageLoading(false);
        });
      Promise.all([overallP, byStageP]).then(([m]) => {
        if (!signal.aborted) void snapshot(m);
      });
    } else {
      setByStage(null);
    }
    return () => controller.abort();
  }, [applied]);

  const canCompute = draft.source === "labels" ? draft.datasetIds.length > 0 : runs.length > 0;
  const dirty = !applied || !sameSettings(draft, applied) || applied.refresh;

  const compute = (refresh: boolean) => {
    if (!canCompute) return;
    setApplied((prev) => ({ ...draft, refresh, nonce: (prev?.nonce ?? 0) + 1 }));
  };
  const recompute = () => {
    if (!applied) return;
    setApplied((prev) => (prev ? { ...prev, refresh: true, nonce: prev.nonce + 1 } : prev));
  };

  const showByStage = applied?.source === "labels";
  const computedAt = overall?.computed_at ?? byStage?.computed_at;

  // Cutoffs available for the current view; the selected k falls back to the deepest when unset or
  // not present in this data. Drives the Overall cards/slices/per-case and the by-stage table.
  const availableKs = overall?.ks ?? byStage?.ks ?? [];
  const maxK = availableKs.length ? Math.max(...availableKs) : 10;
  const activeK = selectedK != null && availableKs.includes(selectedK) ? selectedK : maxK;
  const lk = String(activeK);
  const cardValue = (m: MetricDef): number | null | undefined =>
    overall ? m.value(overall, lk) : undefined;
  const metCount = useMemo(
    () =>
      overall && targets
        ? METRICS.filter((m) => statusOf(cardValue(m), targets[m.key]) === "good").length
        : 0,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [overall, targets, lk],
  );

  const toggleClass = (active: boolean) =>
    `px-2.5 py-1.5 ${
      active
        ? "bg-indigo-600 text-white"
        : "bg-white dark:bg-slate-900 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
    }`;

  return (
    <div className="mt-12">
      <div className="flex items-center justify-between gap-4 mb-1 flex-wrap">
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-bold">Retrieval quality</h2>
          <Info text={EXPLAIN.targets} />
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700 text-xs">
            {(["urls", "labels"] as const).map((s) => (
              <button key={s} onClick={() => setDraftField("source", s)} className={toggleClass(draft.source === s)}>
                {s === "urls" ? "Expected URLs" : "Human labels"}
              </button>
            ))}
          </div>
          {draft.source === "labels" && (
            <div
              className="flex items-center gap-1.5 text-xs"
              title="Which chunk labels resolve the gold: human only, the AI judge only, or both"
            >
              <span className="text-gray-400 dark:text-slate-500">Gold</span>
              <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700">
                {(["human", "ai", "both"] as const).map((g) => (
                  <button key={g} onClick={() => setDraftField("goldSource", g)} className={`${toggleClass(draft.goldSource === g)} capitalize`}>
                    {g === "ai" ? "AI" : g}
                  </button>
                ))}
              </div>
            </div>
          )}
          {overall?.available && targets && (
            <span
              className={`text-xs font-medium px-2 py-1 rounded-full ${
                metCount === METRICS.length
                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : "bg-amber-500/10 text-amber-600 dark:text-amber-400"
              }`}
            >
              {metCount} / {METRICS.length} targets met
            </span>
          )}
          {draft.source === "labels"
            ? datasets.length > 0 && (
                <DatasetMultiSelect
                  datasets={datasets}
                  selected={draft.datasetIds}
                  onChange={(ids) => setDraftField("datasetIds", ids)}
                />
              )
            : runs.length > 0 && (
                <select
                  value={draft.runId ?? ""}
                  onChange={(e) => setDraftField("runId", e.target.value || null)}
                  className="text-sm rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 max-w-[260px]"
                >
                  {runs.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              )}
          <button
            onClick={() => compute(false)}
            disabled={!canCompute || loading || (!dirty && !!applied)}
            className={`text-sm font-medium rounded-lg px-4 py-1.5 ${
              dirty && canCompute
                ? "bg-indigo-600 text-white hover:bg-indigo-700"
                : "bg-gray-100 dark:bg-slate-800 text-gray-400 dark:text-slate-500"
            } disabled:opacity-60`}
            title={
              draft.source === "labels" && draft.datasetIds.length === 0
                ? "Select at least one dataset"
                : "Compute retrieval metrics for the chosen settings"
            }
          >
            {loading ? "Computing…" : applied ? "Compute" : "Compute metrics"}
          </button>
        </div>
      </div>

      <p className="text-sm text-gray-500 dark:text-slate-400 mb-5 max-w-3xl">
        {draft.source === "labels" ? (
          <>
            Measured against human chunk relevance labels vs. a live retrieval probe of the
            connected index, per dataset. Recall@k = share of judged-relevant chunks the index
            returns in the top-k; bpref and condensed nDCG stay fair while judging is still
            incomplete.
          </>
        ) : (
          <>
            Measured against your test cases&apos; ground-truth source URLs, per eval run.
            Recall@k = share of expected docs found in the top-k retrieved; nDCG rewards ranking
            them high; MRR = how early the first relevant doc shows up.
          </>
        )}
      </p>

      {error ? <ErrorNotice error={error} className="mb-4" /> : null}

      {/* Results header: cutoff selector + when the numbers were computed + a Recompute action. */}
      {applied && (computedAt || loading) && (
        <div className="flex items-center justify-between gap-3 mb-3">
          <div className="flex items-center gap-3 flex-wrap">
            {(overall?.available || byStage?.available) && (
              <KSelector ks={availableKs} value={activeK} onChange={setSelectedK} />
            )}
            {dirty && applied && !loading && (
              <span className="text-xs text-amber-600 dark:text-amber-400">
                Settings changed — press Compute to update.
              </span>
            )}
          </div>
          <ComputedAt at={computedAt} onRecompute={recompute} busy={loading} />
        </div>
      )}

      {!applied ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          Choose your source, datasets and gold above, then press{" "}
          <span className="font-medium text-gray-700 dark:text-slate-200">Compute metrics</span>.
        </div>
      ) : (
        <>
          {/* Overall — the single best-available ranking. */}
          {savedRun && applied.source === "labels" && (
            <RunMetadataEditor
              run={savedRun}
              canEdit={canEdit}
              onSaved={(u) => {
                setSavedRun(u);
                onRunSaved?.();
              }}
            />
          )}
          {loading && !overall ? (
            <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
              Computing retrieval metrics...
            </div>
          ) : !overall || !overall.available ? (
            <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
              {applied.source === "labels" ? (
                <>
                  No chunk relevance labels for these datasets yet, or no index is connected to
                  probe. Judge candidates on the Labeling page (and connect an index provider), then
                  this measures the index&apos;s recall against those human labels.
                </>
              ) : (
                <>
                  No labeled retrieval data for this run. Add expected source URLs to test cases and
                  run an evaluation with a <span className="font-mono">contains_urls</span> check to
                  measure recall.
                </>
              )}
            </div>
          ) : (
            <OverallResults
              overall={overall}
              targets={targets}
              activeK={activeK}
              source={applied.source}
            />
          )}

          {/* By stage — each retrieval method scored separately (labels path only). */}
          {showByStage && (
            <div className="mt-10">
              <h3 className="text-base font-semibold mb-3">By stage</h3>
              {byStageError ? <ErrorNotice error={byStageError} className="mb-3" /> : null}
              <ByStageComparison
                data={byStage}
                loading={byStageLoading}
                goldSource={applied.goldSource}
                selectedK={activeK}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
