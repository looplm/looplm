"use client";

import { useEffect, useState } from "react";
import {
  getDatasets,
  getEvalRuns,
  getRetrievalMetrics,
  getRetrievalTargets,
  type EvalRunListItem,
  type RetrievalRunMetrics,
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

export default function RetrievalMetricsPanel() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("pipeline");

  const [runs, setRuns] = useState<EvalRunListItem[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  // Datasets drive the "Human labels" source (labels vs a live retrieval probe, per dataset).
  const [datasets, setDatasets] = useState<{ id: string; name: string }[]>([]);
  // Datasets to aggregate the label-based views over ([] = most recent, the backend default).
  const [datasetIds, setDatasetIds] = useState<string[]>([]);
  const [source, setSource] = useState<"urls" | "labels">("urls");
  // Which chunk labels resolve the gold (labels source only): human only, AI judge only, or both.
  const [goldSource, setGoldSource] = useState<"human" | "ai" | "both">("human");
  // Labels source view: the overall system metrics, or the per-stage comparison.
  const [labelsView, setLabelsView] = useState<"overall" | "byStage">("overall");
  const [metrics, setMetrics] = useState<RetrievalRunMetrics | null>(null);
  const [targets, setTargets] = useState<RetrievalTargets | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getEvalRuns({ limit: "50" })
      .then((res) => setRuns(res.data))
      .catch(() => setRuns([]));
    getDatasets({ per_page: "100" })
      .then((res) => setDatasets(res.data.map((d) => ({ id: d.id, name: d.name }))))
      .catch(() => setDatasets([]));
    getRetrievalTargets()
      .then(setTargets)
      .catch(() => setTargets(null));
  }, []);

  useEffect(() => {
    // The per-stage view fetches its own data; skip the overall metrics request while it's shown.
    if (source === "labels" && labelsView === "byStage") {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const req =
      source === "labels"
        ? getRetrievalMetrics({ datasetIds, source: "labels", goldSource })
        : getRetrievalMetrics({ runId: runId ?? undefined, source: "urls" });
    req
      .then((m) => {
        if (cancelled) return;
        setMetrics(m);
        // On the URLs path the response reports the run it defaulted to; seed the run picker.
        if (source !== "labels" && !runId && m.run_id) setRunId(m.run_id);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, datasetIds, source, goldSource, labelsView]);

  const largestK = metrics?.ks.length ? Math.max(...metrics.ks) : 10;
  const lk = String(largestK);

  const cardValue = (m: MetricDef): number | null | undefined =>
    metrics ? m.value(metrics, lk) : undefined;

  const metCount =
    metrics && targets
      ? METRICS.filter((m) => statusOf(cardValue(m), targets[m.key]) === "good").length
      : 0;

  return (
    <div className="mt-12">
      <div className="flex items-center justify-between gap-4 mb-1">
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-bold">Retrieval quality</h2>
          <Info text={EXPLAIN.targets} />
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700 text-xs">
            {(["urls", "labels"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSource(s)}
                className={`px-2.5 py-1.5 ${
                  source === s
                    ? "bg-indigo-600 text-white"
                    : "bg-white dark:bg-slate-900 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
                }`}
              >
                {s === "urls" ? "Expected URLs" : "Human labels"}
              </button>
            ))}
          </div>
          {source === "labels" && (
            <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700 text-xs">
              {(["overall", "byStage"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setLabelsView(v)}
                  className={`px-2.5 py-1.5 ${
                    labelsView === v
                      ? "bg-indigo-600 text-white"
                      : "bg-white dark:bg-slate-900 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
                  }`}
                >
                  {v === "overall" ? "Overall" : "By stage"}
                </button>
              ))}
            </div>
          )}
          {source === "labels" && (
            <div
              className="flex items-center gap-1.5 text-xs"
              title="Which chunk labels resolve the gold: human only, the AI judge only, or both"
            >
              <span className="text-gray-400 dark:text-slate-500">Gold</span>
              <div className="flex rounded-lg overflow-hidden border border-gray-200 dark:border-slate-700">
                {(["human", "ai", "both"] as const).map((g) => (
                  <button
                    key={g}
                    onClick={() => setGoldSource(g)}
                    className={`px-2.5 py-1.5 capitalize ${
                      goldSource === g
                        ? "bg-indigo-600 text-white"
                        : "bg-white dark:bg-slate-900 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
                    }`}
                  >
                    {g === "ai" ? "AI" : g}
                  </button>
                ))}
              </div>
            </div>
          )}
          {metrics?.available && targets && (
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
          {source === "labels"
            ? datasets.length > 0 && (
                <>
                  {canEdit && (
                    <JudgeAllButton
                      datasets={datasets}
                      selectedIds={datasetIds}
                      onDone={() => setReloadKey((k) => k + 1)}
                    />
                  )}
                  <DatasetMultiSelect
                    datasets={datasets}
                    selected={datasetIds}
                    onChange={setDatasetIds}
                  />
                </>
              )
            : runs.length > 0 && (
                <select
                  value={runId ?? ""}
                  onChange={(e) => setRunId(e.target.value || null)}
                  className="text-sm rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 max-w-[260px]"
                >
                  {runs.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              )}
        </div>
      </div>
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-5 max-w-3xl">
        {source === "labels" ? (
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

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      )}

      {source === "labels" && labelsView === "byStage" ? (
        <ByStageComparison key={reloadKey} datasetIds={datasetIds} goldSource={goldSource} />
      ) : loading ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          Computing retrieval metrics...
        </div>
      ) : !metrics || !metrics.available ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-10 text-center text-gray-500 dark:text-slate-400">
          {source === "labels" ? (
            <>
              No chunk relevance labels for this dataset yet, or no index is connected to probe.
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
          <div className="text-xs text-gray-400 dark:text-slate-500 mb-3">
            {metrics.evaluated_cases} of {metrics.total_cases} cases have{" "}
            {source === "labels" ? "relevance labels" : "ground-truth URLs"}
          </div>

          <ReliabilityBanner count={metrics.evaluated_cases} source={source} />

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
          {source === "labels" && metrics.bpref != null && (
            <div className="mb-4">
              <div className="flex items-center text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-2">
                Robust to incomplete judging
              </div>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <MetricCard
                  label="bpref"
                  value={metrics.bpref}
                  target={null}
                  kind="pct"
                  hint="ignores unjudged"
                  accent="violet"
                  info={EXPLAIN.bpref}
                />
                <MetricCard
                  label={`cNDCG@${largestK}`}
                  value={metrics.condensed_ndcg_at_k?.[lk]}
                  target={null}
                  kind="pct"
                  hint="judged-only ranking"
                  accent="violet"
                  info={EXPLAIN.cndcg}
                />
              </div>
            </div>
          )}

          {metrics.slices && metrics.slices.length > 0 && (
            <SliceBreakdown slices={metrics.slices} largestK={largestK} />
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 items-stretch">
            <RecallCurve recall={metrics.recall_at_k} ks={metrics.ks} target={targets ? targets.recall : null} />

            <PerCaseResults
              cases={metrics.cases}
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
