"use client";

import { useEffect, useState } from "react";
import {
  getEvalRuns,
  getRetrievalMetrics,
  type EvalRunListItem,
  type RetrievalRunMetrics,
} from "@/lib/api";

function pct(x: number | null | undefined): string {
  return x == null ? "—" : `${Math.round(x * 100)}%`;
}

function dec(x: number | null | undefined): string {
  return x == null ? "—" : x.toFixed(2);
}

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-gray-400 dark:text-slate-500">{label}</div>
      <div className="text-2xl font-semibold text-gray-900 dark:text-white mt-0.5">{value}</div>
      {hint && <div className="text-[10px] text-gray-400 dark:text-slate-500 mt-0.5">{hint}</div>}
    </div>
  );
}

function RecallCurve({ recall, ks }: { recall: Record<string, number>; ks: number[] }) {
  return (
    <div className="rounded-lg border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
      <div className="text-[11px] uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-3">
        Recall @ k
      </div>
      <div className="flex items-end gap-3 h-28">
        {ks.map((k) => {
          const v = recall[String(k)] ?? 0;
          return (
            <div key={k} className="flex-1 flex flex-col items-center gap-1">
              <div className="text-[10px] font-mono text-gray-500 dark:text-slate-400">{pct(v)}</div>
              <div className="w-full bg-gray-100 dark:bg-slate-800 rounded-sm flex items-end h-full">
                <div
                  className="w-full bg-indigo-500/70 rounded-sm transition-all"
                  style={{ height: `${Math.max(2, v * 100)}%` }}
                />
              </div>
              <div className="text-[10px] text-gray-400 dark:text-slate-500">@{k}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function RetrievalMetricsPanel() {
  const [runs, setRuns] = useState<EvalRunListItem[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<RetrievalRunMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load the run list once for the selector.
  useEffect(() => {
    getEvalRuns({ limit: "50" })
      .then((res) => setRuns(res.data))
      .catch(() => setRuns([]));
  }, []);

  // Fetch metrics for the selected run (or the latest, when none picked yet).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRetrievalMetrics(runId ?? undefined)
      .then((m) => {
        if (!cancelled) {
          setMetrics(m);
          if (!runId && m.run_id) setRunId(m.run_id);
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
  }, [runId]);

  const largestK = metrics?.ks.length ? Math.max(...metrics.ks) : 10;
  const lk = String(largestK);

  return (
    <div className="mt-12">
      <div className="flex items-center justify-between gap-4 mb-1">
        <h2 className="text-xl font-bold">Retrieval quality</h2>
        {runs.length > 0 && (
          <select
            value={runId ?? ""}
            onChange={(e) => setRunId(e.target.value || null)}
            className="text-sm rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 max-w-[280px]"
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        )}
      </div>
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-4 max-w-3xl">
        Measured against your test cases&apos; ground-truth source URLs, per eval run.
        Recall@k = share of expected docs found in the top-k retrieved; nDCG rewards ranking
        them high; MRR = how early the first relevant doc shows up.
      </p>

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
          No labeled retrieval data for this run. Add expected source URLs to test cases and
          run an evaluation with a <span className="font-mono">contains_urls</span> check to
          measure recall.
        </div>
      ) : (
        <>
          <div className="text-xs text-gray-400 dark:text-slate-500 mb-3">
            {metrics.evaluated_cases} of {metrics.total_cases} cases have ground-truth URLs
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-3">
            <MetricCard label={`Recall@${largestK}`} value={pct(metrics.recall_at_k[lk])} hint="docs found" />
            <MetricCard label={`nDCG@${largestK}`} value={pct(metrics.ndcg_at_k[lk])} hint="ranking quality" />
            <MetricCard label="MRR" value={dec(metrics.mrr)} hint="first hit rank" />
            <MetricCard label={`Hit-rate@${largestK}`} value={pct(metrics.hit_rate_at_k[lk])} hint="≥1 relevant" />
            <MetricCard label={`Precision@${largestK}`} value={pct(metrics.precision_at_k[lk])} hint="of retrieved" />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-3">
            <RecallCurve recall={metrics.recall_at_k} ks={metrics.ks} />

            <div className="lg:col-span-2 rounded-lg border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
              <div className="text-[11px] uppercase tracking-wide text-gray-400 dark:text-slate-500 px-4 pt-3 pb-2">
                Worst cases first
              </div>
              <div className="overflow-x-auto max-h-[320px]">
                <table className="w-full text-xs">
                  <thead className="text-gray-400 dark:text-slate-500 border-b border-gray-100 dark:border-slate-800">
                    <tr>
                      <th className="text-left font-medium px-4 py-2">Query</th>
                      <th className="text-right font-medium px-2 py-2">Exp.</th>
                      <th className="text-right font-medium px-2 py-2">Retr.</th>
                      <th className="text-right font-medium px-2 py-2">Recall@{largestK}</th>
                      <th className="text-right font-medium px-2 py-2">1st hit</th>
                      <th className="text-center font-medium px-3 py-2">Hit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.cases.map((c) => (
                      <tr key={c.test_id} className="border-b border-gray-50 dark:border-slate-800/50">
                        <td className="px-4 py-2 max-w-[280px] truncate text-gray-700 dark:text-slate-300" title={c.input ?? c.test_id}>
                          {c.input || c.test_id}
                        </td>
                        <td className="px-2 py-2 text-right font-mono text-gray-500 dark:text-slate-400">{c.expected_count}</td>
                        <td className="px-2 py-2 text-right font-mono text-gray-500 dark:text-slate-400">{c.retrieved_count}</td>
                        <td className="px-2 py-2 text-right font-mono text-gray-700 dark:text-slate-300">{pct(c.recall_at_k[lk])}</td>
                        <td className="px-2 py-2 text-right font-mono text-gray-500 dark:text-slate-400">
                          {c.first_relevant_rank ?? "—"}
                        </td>
                        <td className="px-3 py-2 text-center">
                          <span className={c.hit ? "text-emerald-500" : "text-red-500"}>{c.hit ? "✓" : "✕"}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
