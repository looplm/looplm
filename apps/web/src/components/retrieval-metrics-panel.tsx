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
import { Info, MetricCard } from "@/components/retrieval/metric-card";
import { RecallCurve } from "@/components/retrieval/recall-curve";
import {
  PerCaseResults,
  ReliabilityBanner,
  SliceBreakdown,
} from "@/components/retrieval/retrieval-table";
import { ByStageComparison } from "@/components/retrieval/by-stage-table";
import { DatasetMultiSelect } from "@/components/retrieval/dataset-multiselect";
import { ErrorNotice } from "@/components/error-notice";
import { ComputedAt } from "@/components/retrieval/computed-at";
import { RunMetadataEditor } from "@/components/retrieval/run-metadata-editor";

type Source = "urls" | "labels";
type GoldSource = "human" | "ai" | "both";
type LabelsView = "overall" | "byStage";

// The settings the user is editing. Computation only runs against the *applied* copy (below).
type Draft = {
  source: Source;
  goldSource: GoldSource;
  labelsView: LabelsView;
  datasetIds: string[];
  runId: string | null;
};
// A snapshot of Draft that has been sent to compute, plus a nonce to retrigger the fetch on
// Recompute (same settings, forced refresh) and a refresh flag.
type Applied = Draft & { refresh: boolean; nonce: number };

const sameSettings = (a: Draft, b: Draft): boolean =>
  a.source === b.source &&
  a.goldSource === b.goldSource &&
  a.labelsView === b.labelsView &&
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
    labelsView: "overall",
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
  useEffect(() => {
    if (!applied) return;
    const isByStage = applied.source === "labels" && applied.labelsView === "byStage";
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setSavedRun(null);

    // The labels-path compute (live index probe + embeddings) runs detached on the server so a
    // reload / proxy timeout can't reset the socket mid-flight. Poll the job until it settles;
    // a failed job carries the server error + traceback (debug), surfaced via ErrorNotice.
    const runLabels = async () => {
      const job = await startRetrievalCompute(
        {
          dataset_ids: applied.datasetIds,
          gold_source: applied.goldSource,
          view: isByStage ? "byStage" : "overall",
          refresh: applied.refresh,
        },
        controller.signal,
      );
      await pollRetrievalCompute(job.id, controller.signal);
      if (controller.signal.aborted) return;
      // The job wrote the result into the server cache; read it back without recomputing.
      if (isByStage) {
        const d = await getRetrievalByStageMetrics(
          { datasetIds: applied.datasetIds, goldSource: applied.goldSource, refresh: false },
          controller.signal,
        );
        if (!controller.signal.aborted) setByStage(d);
        return;
      }
      const m = await getRetrievalMetrics(
        { datasetIds: applied.datasetIds, source: "labels", goldSource: applied.goldSource, refresh: false },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setOverall(m);
      // Auto-snapshot the result into durable history (once per Compute/Recompute).
      if (m.available && savedNonceRef.current !== applied.nonce) {
        savedNonceRef.current = applied.nonce;
        try {
          const rec = await createRetrievalRun(
            { dataset_ids: applied.datasetIds, gold_source: applied.goldSource },
            controller.signal,
          );
          if (!controller.signal.aborted) {
            setSavedRun(rec);
            onRunSavedRef.current?.();
          }
        } catch {
          /* history snapshot is best-effort; the metrics still render */
        }
      }
    };

    const runUrls = async () => {
      // URLs path reads a stored eval-run aggregate (no live probe) — fast enough to stay inline.
      const m = await getRetrievalMetrics(
        { runId: applied.runId ?? undefined, source: "urls", refresh: applied.refresh },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setOverall(m);
      if (!applied.runId && m.run_id) setDraftField("runId", m.run_id);
    };

    (applied.source === "labels" ? runLabels() : runUrls())
      .catch((e) => {
        if (controller.signal.aborted || e?.name === "AbortError") return;
        setError(e);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
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

  const showingByStage = applied?.source === "labels" && applied.labelsView === "byStage";
  const computedAt = showingByStage ? byStage?.computed_at : overall?.computed_at;

  const largestK = overall?.ks.length ? Math.max(...overall.ks) : 10;
  const lk = String(largestK);
  const cardValue = (m: MetricDef): number | null | undefined =>
    overall ? m.value(overall, lk) : undefined;
  const metCount = useMemo(
    () =>
      overall && targets
        ? METRICS.filter((m) => statusOf(cardValue(m), targets[m.key]) === "good").length
        : 0,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [overall, targets],
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
            <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700 text-xs">
              {(["overall", "byStage"] as const).map((v) => (
                <button key={v} onClick={() => setDraftField("labelsView", v)} className={toggleClass(draft.labelsView === v)}>
                  {v === "overall" ? "Overall" : "By stage"}
                </button>
              ))}
            </div>
          )}
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
          {overall?.available && targets && !showingByStage && (
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

      {/* Results header: when the numbers were computed + a Recompute action. */}
      {applied && (computedAt || loading) && (
        <div className="flex items-center justify-between mb-3">
          {dirty && applied && !loading ? (
            <span className="text-xs text-amber-600 dark:text-amber-400">
              Settings changed — press Compute to update.
            </span>
          ) : (
            <span />
          )}
          <ComputedAt at={computedAt} onRecompute={recompute} busy={loading} />
        </div>
      )}

      {!applied ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          Choose your source, datasets and gold above, then press{" "}
          <span className="font-medium text-gray-700 dark:text-slate-200">Compute metrics</span>.
        </div>
      ) : showingByStage ? (
        <ByStageComparison data={byStage} loading={loading} goldSource={applied.goldSource} />
      ) : loading && !overall ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          Computing retrieval metrics...
        </div>
      ) : !overall || !overall.available ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          {applied.source === "labels" ? (
            <>
              No chunk relevance labels for these datasets yet, or no index is connected to probe.
              Judge candidates on the Labeling page (and connect an index provider), then this
              measures the index&apos;s recall against those human labels.
            </>
          ) : (
            <>
              No labeled retrieval data for this run. Add expected source URLs to test cases
              and run an evaluation with a <span className="font-mono">contains_urls</span>{" "}
              check to measure recall.
            </>
          )}
        </div>
      ) : (
        <>
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

          <div className="text-xs text-gray-400 dark:text-slate-500 mb-3">
            {overall.evaluated_cases} of {overall.total_cases} cases have{" "}
            {applied.source === "labels" ? "relevance labels" : "ground-truth URLs"}
          </div>

          {/* Which retrieval method these numbers reflect. The Overall view collapses to a single
              ranking, so name it explicitly and point to the by-stage comparison. */}
          <div className="flex items-start gap-2 rounded-lg bg-gray-50 dark:bg-slate-800/40 border border-gray-100 dark:border-slate-800 px-3 py-2 mb-3 text-xs text-gray-500 dark:text-slate-400">
            <Info text={EXPLAIN.method} />
            {applied.source === "labels" ? (
              <span>
                <span className="font-medium text-gray-600 dark:text-slate-300">Method:</span>{" "}
                your live index&apos;s best-available ranking. It prefers the semantic reranker,
                falling back to hybrid (RRF), vector, then keyword.{" "}
                <button
                  onClick={() => setDraftField("labelsView", "byStage")}
                  className="font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
                >
                  Switch to By stage
                </button>{" "}
                to score each method (Sparse, Dense, RRF, Reranked) separately.
              </span>
            ) : (
              <span>
                <span className="font-medium text-gray-600 dark:text-slate-300">Method:</span>{" "}
                your app&apos;s final logged retrieval order, which is post-rerank. A
                before-vs-after-rerank split is not available on this path.
              </span>
            )}
          </div>

          <ReliabilityBanner count={overall.evaluated_cases} source={applied.source} />

          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
            {METRICS.map((m) => (
              <MetricCard
                key={m.key}
                label={m.label(largestK)}
                value={cardValue(m)}
                target={targets ? targets[m.key] : null}
                kind={m.kind}
                hint={m.hint}
                accent={m.accent}
                info={m.info}
              />
            ))}
          </div>

          {/* Incomplete-judgment-safe metrics: only on the human-label path, where the pool
              is partly judged. Shown without targets — they're a robustness cross-check. */}
          {applied.source === "labels" && overall.bpref != null && (
            <div className="mb-4">
              <div className="flex items-center text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-2">
                Robust to incomplete judging
              </div>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <MetricCard
                  label="bpref"
                  value={overall.bpref}
                  target={null}
                  kind="pct"
                  hint="ignores unjudged"
                  accent="violet"
                  info={EXPLAIN.bpref}
                />
                <MetricCard
                  label={`cNDCG@${largestK}`}
                  value={overall.condensed_ndcg_at_k?.[lk]}
                  target={null}
                  kind="pct"
                  hint="judged-only ranking"
                  accent="violet"
                  info={EXPLAIN.cndcg}
                />
              </div>
            </div>
          )}

          {overall.slices && overall.slices.length > 0 && (
            <SliceBreakdown slices={overall.slices} largestK={largestK} />
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 items-stretch">
            <RecallCurve recall={overall.recall_at_k} ks={overall.ks} target={targets ? targets.recall : null} />

            <PerCaseResults
              cases={overall.cases}
              largestK={largestK}
              lk={lk}
              recallTarget={targets ? targets.recall : null}
            />
          </div>
        </>
      )}
    </div>
  );
}
