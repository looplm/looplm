"use client";

import { useEffect, useState } from "react";
import {
  getDatasets,
  getEvalRuns,
  getRetrievalMetrics,
  getRetrievalTargets,
  saveRetrievalTargets,
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

function TargetsEditor({
  targets,
  largestK,
  currentValues,
  onSave,
  onClose,
}: {
  targets: RetrievalTargets;
  largestK: number;
  currentValues: Partial<Record<keyof RetrievalTargets, number | null | undefined>>;
  onSave: (t: RetrievalTargets) => Promise<void>;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<RetrievalTargets>(targets);
  const [saving, setSaving] = useState(false);

  const setVal = (key: keyof RetrievalTargets, v: number) =>
    setDraft((d) => ({ ...d, [key]: Math.max(0, Math.min(1, v)) }));

  const useCurrentRun = () => {
    const next = { ...draft };
    for (const m of METRICS) {
      const v = currentValues[m.key];
      if (typeof v === "number") next[m.key] = v;
    }
    setDraft(next);
  };

  return (
    <div className="mb-4 rounded-xl border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-900/60 p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold">Set targets</span>
        <button
          onClick={useCurrentRun}
          className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
        >
          Use this run&apos;s scores
        </button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {METRICS.map((m) => (
          <label key={m.key} className="block">
            <span className="text-[11px] text-gray-500 dark:text-slate-400">{m.label(largestK)}</span>
            <div className="mt-1 flex items-center gap-1">
              {m.kind === "pct" ? (
                <>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={5}
                    value={Math.round(draft[m.key] * 100)}
                    onChange={(e) => setVal(m.key, Number(e.target.value) / 100)}
                    className="w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-sm tabular-nums"
                  />
                  <span className="text-xs text-gray-400">%</span>
                </>
              ) : (
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={Number(draft[m.key].toFixed(2))}
                  onChange={(e) => setVal(m.key, Number(e.target.value))}
                  className="w-full rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-sm tabular-nums"
                />
              )}
            </div>
          </label>
        ))}
      </div>
      <div className="flex items-center justify-end gap-2 mt-4">
        <button
          onClick={onClose}
          className="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-slate-700 hover:bg-gray-100 dark:hover:bg-slate-800"
        >
          Cancel
        </button>
        <button
          disabled={saving}
          onClick={async () => {
            setSaving(true);
            try {
              await onSave(draft);
              onClose();
            } finally {
              setSaving(false);
            }
          }}
          className="px-3 py-1.5 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-60"
        >
          {saving ? "Saving..." : "Save targets"}
        </button>
      </div>
    </div>
  );
}

export default function RetrievalMetricsPanel() {
  const { canWrite } = usePermissions();
  const canEdit = canWrite("pipeline");

  const [runs, setRuns] = useState<EvalRunListItem[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  // Datasets drive the "Human labels" source (labels vs a live retrieval probe, per dataset).
  const [datasets, setDatasets] = useState<{ id: string; name: string }[]>([]);
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [source, setSource] = useState<"urls" | "labels">("urls");
  // Fold the AI judge's chunk labels into the gold (labels source only).
  const [includeAi, setIncludeAi] = useState(false);
  const [metrics, setMetrics] = useState<RetrievalRunMetrics | null>(null);
  const [targets, setTargets] = useState<RetrievalTargets | null>(null);
  const [editing, setEditing] = useState(false);
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
    let cancelled = false;
    setLoading(true);
    setError(null);
    const req =
      source === "labels"
        ? getRetrievalMetrics({ datasetId: datasetId ?? undefined, source: "labels", includeAi })
        : getRetrievalMetrics({ runId: runId ?? undefined, source: "urls" });
    req
      .then((m) => {
        if (cancelled) return;
        setMetrics(m);
        // The labels path returns the dataset id/name in run_id/run_name; seed the right picker.
        if (source === "labels") {
          if (!datasetId && m.run_id) setDatasetId(m.run_id);
        } else if (!runId && m.run_id) {
          setRunId(m.run_id);
        }
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
  }, [runId, datasetId, source, includeAi]);

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
            <label
              className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-slate-400 cursor-pointer"
              title="Fold the AI judge's chunk labels into the gold as one more annotator"
            >
              <input
                type="checkbox"
                checked={includeAi}
                onChange={(e) => setIncludeAi(e.target.checked)}
                className="rounded border-gray-300 dark:border-slate-600"
              />
              Include AI judge
            </label>
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
          {canEdit && targets && (
            <button
              onClick={() => setEditing((v) => !v)}
              className="text-sm rounded-lg border border-gray-200 dark:border-slate-700 px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-slate-800"
            >
              Targets
            </button>
          )}
          {source === "labels"
            ? datasets.length > 0 && (
                <select
                  value={datasetId ?? ""}
                  onChange={(e) => setDatasetId(e.target.value || null)}
                  className="text-sm rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 max-w-[260px]"
                >
                  {datasets.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
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

      {editing && targets && (
        <TargetsEditor
          targets={targets}
          largestK={largestK}
          currentValues={Object.fromEntries(METRICS.map((m) => [m.key, cardValue(m)]))}
          onSave={async (t) => {
            const saved = await saveRetrievalTargets(t);
            setTargets(saved);
          }}
          onClose={() => setEditing(false)}
        />
      )}

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading ? (
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
