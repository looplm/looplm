"use client";

import { useEffect, useState } from "react";
import {
  getEvalRuns,
  getRetrievalMetrics,
  type EvalRunListItem,
  type RetrievalRunMetrics,
} from "@/lib/api";

function pct(x: number | null | undefined): string {
  return x == null ? "-" : `${Math.round(x * 100)}%`;
}

function dec(x: number | null | undefined): string {
  return x == null ? "-" : x.toFixed(2);
}

// Plain-language explanations shown on the info icons (kept simple, no jargon).
const EXPLAIN = {
  recall:
    "Of all the documents that should have been found, this is the share that showed up in the top results. Higher is better.",
  ndcg:
    "Checks whether the most useful documents are ranked near the top, not just present somewhere. 100% means the best ones sit at the very top.",
  mrr:
    "Looks at how high the first correct document appears. 1.00 means it was always the very first result, 0.50 means usually second, and so on.",
  hit:
    "The share of questions where at least one correct document appeared in the top results. It does not care how many were found, only that one was there.",
  precision:
    "Of the documents that were returned, this is the share that were actually relevant. Higher means less noise in the results.",
  recallCurve:
    "How many of the correct documents appear as you widen the window from the top 1 result out to the top 10. The bars normally rise as k grows.",
  expected: "How many documents this question was expected to find (the ground truth).",
  retrieved: "How many documents the search actually returned for this question.",
  caseRecall: "The share of the expected documents that were found for this single question.",
  firstHit: "The position of the first correct document in the results. Lower is better. A dash means none were found.",
};

function Info({ text }: { text: string }) {
  return (
    <span
      title={text}
      role="img"
      aria-label={text}
      className="ml-1 inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-gray-300 dark:border-slate-600 text-gray-400 dark:text-slate-500 text-[9px] font-semibold leading-none cursor-help align-middle hover:border-gray-400 hover:text-gray-600 dark:hover:border-slate-400 dark:hover:text-slate-300"
    >
      i
    </span>
  );
}

type Accent = "indigo" | "violet" | "sky" | "emerald" | "amber";

const ACCENT: Record<Accent, { text: string; bar: string; soft: string }> = {
  indigo: { text: "text-indigo-600 dark:text-indigo-400", bar: "bg-indigo-500", soft: "bg-indigo-500/10" },
  violet: { text: "text-violet-600 dark:text-violet-400", bar: "bg-violet-500", soft: "bg-violet-500/10" },
  sky: { text: "text-sky-600 dark:text-sky-400", bar: "bg-sky-500", soft: "bg-sky-500/10" },
  emerald: { text: "text-emerald-600 dark:text-emerald-400", bar: "bg-emerald-500", soft: "bg-emerald-500/10" },
  amber: { text: "text-amber-600 dark:text-amber-400", bar: "bg-amber-500", soft: "bg-amber-500/10" },
};

function MetricCard({
  label,
  value,
  hint,
  accent,
  info,
}: {
  label: string;
  value: string;
  hint?: string;
  accent: Accent;
  info: string;
}) {
  const a = ACCENT[accent];
  return (
    <div className="relative overflow-hidden rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-3.5">
      <div className={`absolute inset-x-0 top-0 h-0.5 ${a.bar}`} />
      <div className="flex items-center text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500">
        {label}
        <Info text={info} />
      </div>
      <div className={`text-3xl font-bold mt-1 tabular-nums ${a.text}`}>{value}</div>
      {hint && <div className="text-[11px] text-gray-400 dark:text-slate-500 mt-1">{hint}</div>}
    </div>
  );
}

function RecallCurve({ recall, ks }: { recall: Record<string, number>; ks: number[] }) {
  return (
    <div className="flex flex-col h-full rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
      <div className="flex items-center text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-4">
        Recall @ k
        <Info text={EXPLAIN.recallCurve} />
      </div>

      {/* Plot fills remaining card height; bars size as % of this flex-1 area. */}
      <div className="relative flex-1 min-h-[140px]">
        {/* gridlines */}
        {[0.25, 0.5, 0.75, 1].map((g) => (
          <div
            key={g}
            className="absolute inset-x-0 border-t border-dashed border-gray-100 dark:border-slate-800"
            style={{ bottom: `${g * 100}%` }}
          />
        ))}
        <div className="absolute inset-0 flex items-end gap-3">
          {ks.map((k) => {
            const v = recall[String(k)] ?? 0;
            return (
              <div key={k} className="group flex-1 h-full flex flex-col justify-end items-center">
                <div className="text-[11px] font-mono font-semibold text-gray-600 dark:text-slate-300 mb-1 tabular-nums">
                  {pct(v)}
                </div>
                <div
                  className="w-full max-w-[44px] rounded-t-md bg-gradient-to-t from-indigo-500 to-indigo-400 transition-all group-hover:from-indigo-600 group-hover:to-indigo-500"
                  style={{ height: `${Math.max(1.5, v * 100)}%` }}
                />
              </div>
            );
          })}
        </div>
      </div>

      {/* axis */}
      <div className="flex gap-3 mt-2 pt-2 border-t border-gray-100 dark:border-slate-800">
        {ks.map((k) => (
          <div key={k} className="flex-1 text-center text-[11px] font-mono text-gray-400 dark:text-slate-500">
            @{k}
          </div>
        ))}
      </div>
    </div>
  );
}

function MiniBar({ v, accent }: { v: number; accent: Accent }) {
  const a = ACCENT[accent];
  return (
    <div className="flex items-center justify-end gap-2">
      <div className="w-14 h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full ${a.bar}`} style={{ width: `${Math.max(2, v * 100)}%` }} />
      </div>
      <span className="font-mono tabular-nums text-gray-700 dark:text-slate-300 w-9 text-right">{pct(v)}</span>
    </div>
  );
}

export default function RetrievalMetricsPanel() {
  const [runs, setRuns] = useState<EvalRunListItem[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<RetrievalRunMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getEvalRuns({ limit: "50" })
      .then((res) => setRuns(res.data))
      .catch(() => setRuns([]));
  }, []);

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
            className="text-sm rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 max-w-[280px]"
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        )}
      </div>
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-5 max-w-3xl">
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

          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
            <MetricCard accent="indigo" label={`Recall@${largestK}`} value={pct(metrics.recall_at_k[lk])} hint="docs found" info={EXPLAIN.recall} />
            <MetricCard accent="violet" label={`nDCG@${largestK}`} value={pct(metrics.ndcg_at_k[lk])} hint="ranking quality" info={EXPLAIN.ndcg} />
            <MetricCard accent="sky" label="MRR" value={dec(metrics.mrr)} hint="first hit rank" info={EXPLAIN.mrr} />
            <MetricCard accent="emerald" label={`Hit-rate@${largestK}`} value={pct(metrics.hit_rate_at_k[lk])} hint="≥1 relevant" info={EXPLAIN.hit} />
            <MetricCard accent="amber" label={`Precision@${largestK}`} value={pct(metrics.precision_at_k[lk])} hint="of retrieved" info={EXPLAIN.precision} />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 items-stretch">
            <RecallCurve recall={metrics.recall_at_k} ks={metrics.ks} />

            <div className="lg:col-span-2 flex flex-col rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
              <div className="flex items-center justify-between px-4 pt-4 pb-2">
                <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500">
                  Per-case results
                </span>
                <span className="text-[11px] text-gray-400 dark:text-slate-500">worst recall first</span>
              </div>
              <div className="overflow-y-auto flex-1 max-h-[360px]">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-white dark:bg-slate-900 text-gray-400 dark:text-slate-500 border-b border-gray-100 dark:border-slate-800">
                    <tr>
                      <th className="text-left font-medium px-4 py-2">Query</th>
                      <th className="text-right font-medium px-2 py-2">
                        <span className="inline-flex items-center">Exp<Info text={EXPLAIN.expected} /></span>
                      </th>
                      <th className="text-right font-medium px-2 py-2">
                        <span className="inline-flex items-center">Retr<Info text={EXPLAIN.retrieved} /></span>
                      </th>
                      <th className="text-right font-medium px-3 py-2">
                        <span className="inline-flex items-center">Recall@{largestK}<Info text={EXPLAIN.caseRecall} /></span>
                      </th>
                      <th className="text-right font-medium px-2 py-2">
                        <span className="inline-flex items-center">1st hit<Info text={EXPLAIN.firstHit} /></span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.cases.map((c) => (
                      <tr
                        key={c.test_id}
                        className="border-b border-gray-50 dark:border-slate-800/50 hover:bg-gray-50/60 dark:hover:bg-slate-800/30"
                      >
                        <td className="px-4 py-2.5 max-w-[280px]">
                          <div className="flex items-center gap-2">
                            <span
                              className={`shrink-0 w-1.5 h-1.5 rounded-full ${c.hit ? "bg-emerald-500" : "bg-red-500"}`}
                            />
                            <span className="truncate text-gray-700 dark:text-slate-300" title={c.input ?? c.test_id}>
                              {c.input || c.test_id}
                            </span>
                          </div>
                        </td>
                        <td className="px-2 py-2.5 text-right font-mono tabular-nums text-gray-500 dark:text-slate-400">{c.expected_count}</td>
                        <td className="px-2 py-2.5 text-right font-mono tabular-nums text-gray-500 dark:text-slate-400">{c.retrieved_count}</td>
                        <td className="px-3 py-2.5">
                          <MiniBar v={c.recall_at_k[lk] ?? 0} accent={c.hit ? "indigo" : "amber"} />
                        </td>
                        <td className="px-2 py-2.5 text-right font-mono tabular-nums text-gray-500 dark:text-slate-400">
                          {c.first_relevant_rank ?? "-"}
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
