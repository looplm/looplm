"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  createRetrievalRun,
  getDatasets,
  getEvalRuns,
  getRetrievalByStageMetrics,
  getRetrievalMetrics,
  getRetrievalRun,
  getRetrievalTargets,
  pollRetrievalCompute,
  startRetrievalCompute,
  type ByStageMetricsResponse,
  type EvalRunListItem,
  type RetrievalRunMetrics,
  type RetrievalRunRecord,
  type RetrievalTargets,
} from "@/lib/api";
import {
  DEFAULT_RETRIEVER,
  EXPLAIN,
  METRICS,
  RETRIEVERS,
  RETRIEVER_NOTES,
  statusOf,
  type MetricDef,
} from "@/components/retrieval/constants";
import { Info } from "@/components/retrieval/metric-card";
import { OverallSection } from "@/components/retrieval/overall-section";
import { RecommendationsPanel } from "@/components/retrieval/recommendations-panel";
import { ByStageComparison } from "@/components/retrieval/by-stage-table";
import { DatasetMultiSelect } from "@/components/retrieval/dataset-multiselect";
import { GoldControls, type GoldSource, type MinGrade } from "@/components/retrieval/gold-controls";
import { KSelector } from "@/components/retrieval/k-selector";
import { RetrieverSelector } from "@/components/retrieval/retriever-selector";
import { RerankThreshold } from "@/components/retrieval/rerank-threshold";
import { SourceDescription } from "@/components/retrieval/source-description";
import { ErrorNotice } from "@/components/error-notice";
import { ComputedAt } from "@/components/retrieval/computed-at";

type Source = "urls" | "labels";

// The settings the user is editing. Computation only runs against the *applied* copy (below).
// The labels path always computes and shows both the Overall and By-stage views together.
type Draft = {
  source: Source;
  goldSource: GoldSource;
  minGrade: MinGrade;
  datasetIds: string[];
  runId: string | null;
};
// A snapshot of Draft that has been sent to compute, plus a nonce to retrigger the fetch on
// Recompute (same settings, forced refresh) and a refresh flag.
type Applied = Draft & { refresh: boolean; nonce: number };

const sameSettings = (a: Draft, b: Draft): boolean =>
  a.source === b.source &&
  a.goldSource === b.goldSource &&
  a.minGrade === b.minGrade &&
  a.runId === b.runId &&
  a.datasetIds.length === b.datasetIds.length &&
  a.datasetIds.every((id) => b.datasetIds.includes(id));

export default function RetrievalMetricsPanel({
  onRunSaved,
  viewRunId,
  onViewRunChange,
  onDisplayedRunChange,
}: {
  onRunSaved?: () => void;
  // The saved run to display (from the history list); null shows a fresh/empty panel.
  viewRunId?: string | null;
  // Asked to change which run is displayed (e.g. after a fresh compute snapshots a new run).
  onViewRunChange?: (id: string | null) => void;
  // The run record currently displayed (labels path), so the page can render its annotate editor
  // below the panel; null when nothing labels-based is shown.
  onDisplayedRunChange?: (run: RetrievalRunRecord | null) => void;
} = {}) {

  const [runs, setRuns] = useState<EvalRunListItem[]>([]);
  const [datasets, setDatasets] = useState<{ id: string; name: string }[]>([]);
  const [targets, setTargets] = useState<RetrievalTargets | null>(null);

  const [draft, setDraft] = useState<Draft>({
    source: "labels",
    goldSource: "human",
    minGrade: 1,
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
  // Which retriever the Overall block reflects (default Agentic). Display-only; every retriever's
  // metrics are already in the response.
  const [selectedRetriever, setSelectedRetriever] = useState<string>(DEFAULT_RETRIEVER);
  // The run auto-snapshotted from the current Overall compute, for inline metadata annotation.
  const [savedRun, setSavedRun] = useState<RetrievalRunRecord | null>(null);
  const savedNonceRef = useRef<number | null>(null);
  // Keep the latest callbacks without making them effect dependencies (would re-run each render).
  const onRunSavedRef = useRef(onRunSaved);
  onRunSavedRef.current = onRunSaved;
  const onViewRunChangeRef = useRef(onViewRunChange);
  onViewRunChangeRef.current = onViewRunChange;
  const onDisplayedRunChangeRef = useRef(onDisplayedRunChange);
  onDisplayedRunChangeRef.current = onDisplayedRunChange;
  // The run id whose stored data is currently displayed, so we don't refetch a run we just showed
  // (including the one a fresh compute just snapshotted).
  const loadedRunIdRef = useRef<string | null>(null);

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
        { dataset_ids: applied.datasetIds, gold_source: applied.goldSource, min_grade: applied.minGrade, view: "overall", refresh: applied.refresh },
        signal,
      );
      await pollRetrievalCompute(job.id, signal);
      if (signal.aborted) return null;
      const m = await getRetrievalMetrics(
        { datasetIds: applied.datasetIds, source: "labels", goldSource: applied.goldSource, minGrade: applied.minGrade, refresh: false },
        signal,
      );
      if (!signal.aborted) setOverall(m);
      return m;
    };

    const runByStage = async () => {
      const job = await startRetrievalCompute(
        { dataset_ids: applied.datasetIds, gold_source: applied.goldSource, min_grade: applied.minGrade, view: "byStage", refresh: applied.refresh },
        signal,
      );
      await pollRetrievalCompute(job.id, signal);
      if (signal.aborted) return;
      const d = await getRetrievalByStageMetrics(
        { datasetIds: applied.datasetIds, goldSource: applied.goldSource, minGrade: applied.minGrade, refresh: false },
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
          { dataset_ids: applied.datasetIds, gold_source: applied.goldSource, min_grade: applied.minGrade },
          signal,
        );
        if (!signal.aborted) {
          setSavedRun(rec);
          // The fresh result is already on screen; mark this run as displayed and select it in the
          // history so the load-run effect skips a redundant refetch.
          loadedRunIdRef.current = rec.id;
          onViewRunChangeRef.current?.(rec.id);
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

  // Display a saved run's stored metrics/by-stage (from the history list, or the default latest).
  // No recompute — the blobs are read straight off the run. Skips a run we already show (e.g. the
  // one a fresh compute just snapshotted). Setting applied=null exits fresh-compute mode.
  useEffect(() => {
    if (!viewRunId || viewRunId === loadedRunIdRef.current) return;
    const controller = new AbortController();
    getRetrievalRun(viewRunId, controller.signal)
      .then((rec) => {
        if (controller.signal.aborted) return;
        loadedRunIdRef.current = rec.id;
        savedNonceRef.current = null;
        setApplied(null);
        setError(null);
        setByStageError(null);
        setLoading(false);
        setByStageLoading(false);
        setOverall(rec.metrics ?? null);
        setByStage(rec.by_stage ?? null);
        setSavedRun(rec);
        setDraft((d) => ({
          ...d,
          source: "labels",
          goldSource: (rec.gold_source as GoldSource) || "human",
          minGrade: (rec.min_grade as MinGrade) || 1,
          datasetIds: rec.dataset_ids,
        }));
      })
      .catch(() => {
        /* a deleted/invalid run just leaves the current view in place */
      });
    return () => controller.abort();
  }, [viewRunId]);

  // Surface the displayed run to the page, which renders its annotate editor below the panel.
  useEffect(() => {
    onDisplayedRunChangeRef.current?.(savedRun);
  }, [savedRun]);

  const canCompute = draft.source === "labels" ? draft.datasetIds.length > 0 : runs.length > 0;
  const dirty = !applied || !sameSettings(draft, applied) || applied.refresh;

  const compute = (refresh: boolean) => {
    if (!canCompute) return;
    setApplied((prev) => ({ ...draft, refresh, nonce: (prev?.nonce ?? 0) + 1 }));
  };
  const recompute = () => {
    // Viewing a saved run (no applied): run fresh with the run's settings, already synced to draft.
    if (!applied) {
      compute(true);
      return;
    }
    setApplied((prev) => (prev ? { ...prev, refresh: true, nonce: prev.nonce + 1 } : prev));
  };

  // What's on screen: a fresh compute (applied) or a saved run being viewed (savedRun). null → the
  // initial empty prompt. Viewed runs are always the labels path.
  const displaySource: Source | null = applied?.source ?? (savedRun ? "labels" : null);
  const displayGold: GoldSource =
    applied?.goldSource ?? (savedRun?.gold_source as GoldSource) ?? "human";
  const displayMinGrade: MinGrade =
    applied?.minGrade ?? (savedRun?.min_grade as MinGrade) ?? 1;
  const showByStage = displaySource === "labels";
  const computedAt = overall?.computed_at ?? byStage?.computed_at;

  // The Overall block reflects the selected retriever. "best" (and the URLs path) use the live-probe
  // overall; a pipeline stage uses that stage's full metrics from the by-stage response.
  const useBest = displaySource !== "labels" || selectedRetriever === "best";
  const displayMetrics: RetrievalRunMetrics | null = useBest
    ? overall
    : byStage?.stages.find((s) => s.stage === selectedRetriever)?.metrics ?? null;
  const displayLoading = useBest ? loading : byStageLoading;
  const retrieverLabel = RETRIEVERS.find((r) => r.value === selectedRetriever)?.label;
  // The rerankerScore threshold sweep, present only when the Agentic + rerank stage is selected.
  const rerankSweep =
    selectedRetriever === "agentic_rerank"
      ? byStage?.stages.find((s) => s.stage === "agentic_rerank")?.threshold_sweep
      : undefined;

  // Cutoffs available for the displayed retriever; the selected k falls back to the deepest when
  // unset or not present in this data. Drives the Overall cards/curve/per-case and the by-stage table.
  const availableKs = displayMetrics?.ks ?? overall?.ks ?? byStage?.ks ?? [];
  const maxK = availableKs.length ? Math.max(...availableKs) : 10;
  // Default to @10 (the depth typically fed to the model): precision@50 is capped by pool size and
  // reads as noise. Fall back to the deepest cutoff for odd runs that don't compute k=10.
  const defaultK = availableKs.includes(10) ? 10 : maxK;
  const activeK = selectedK != null && availableKs.includes(selectedK) ? selectedK : defaultK;
  const lk = String(activeK);
  const cardValue = (m: MetricDef): number | null | undefined =>
    displayMetrics ? m.value(displayMetrics, lk) : undefined;
  const metCount = useMemo(
    () =>
      displayMetrics && targets
        ? METRICS.filter((m) => statusOf(cardValue(m), targets[m.key]) === "good").length
        : 0,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [displayMetrics, targets, lk],
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
            <GoldControls
              goldSource={draft.goldSource}
              minGrade={draft.minGrade}
              onGoldSource={(g) => setDraftField("goldSource", g)}
              onMinGrade={(g) => setDraftField("minGrade", g)}
            />
          )}
          {displayMetrics?.available && targets && (
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

      <SourceDescription source={draft.source} />

      {error ? <ErrorNotice error={error} className="mb-4" /> : null}

      {/* Results header: retriever + cutoff selectors, when computed, and a Recompute action. */}
      {displaySource && (computedAt || loading || byStageLoading) && (
        <div className="flex items-center justify-between gap-3 mb-3">
          <div className="flex items-center gap-3 flex-wrap">
            {showByStage && (
              <RetrieverSelector
                options={RETRIEVERS}
                value={selectedRetriever}
                onChange={setSelectedRetriever}
              />
            )}
            {displayMetrics?.available && (
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

      {!displaySource ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          Choose your source, datasets and gold above, then press{" "}
          <span className="font-medium text-gray-700 dark:text-slate-200">Compute metrics</span>.
        </div>
      ) : (
        <>
          {/* What to improve — rule-based findings over the computed metrics, most-severe first. */}
          <RecommendationsPanel
            overall={displayMetrics}
            byStage={showByStage ? byStage : null}
            targets={targets}
            k={activeK}
            source={displaySource}
          />

          {/* Score-threshold cutoff explorer — Agentic + rerank only. */}
          {showByStage && rerankSweep && rerankSweep.length > 0 && (
            <RerankThreshold sweep={rerankSweep} precisionTarget={targets?.precision ?? null} />
          )}

          {/* Overall — the selected retriever, in detail. */}
          <OverallSection
            metrics={displayMetrics}
            loading={displayLoading}
            source={displaySource}
            activeK={activeK}
            targets={targets}
            retrieverLabel={retrieverLabel}
            retrieverNote={RETRIEVER_NOTES[selectedRetriever]}
            retriever={selectedRetriever}
            goldSource={displayGold}
            minGrade={displayMinGrade}
            perRetriever={!useBest}
            bestAvailable={!!overall?.available}
          />

          {/* By stage — each retrieval method scored separately (labels path only). */}
          {showByStage && (
            <div id="retrieval-by-stage" className="mt-10">
              <h3 className="text-base font-semibold mb-3">By stage</h3>
              {byStageError ? <ErrorNotice error={byStageError} className="mb-3" /> : null}
              <ByStageComparison
                data={byStage}
                loading={byStageLoading}
                goldSource={displayGold}
                selectedK={activeK}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
