"use client";

import Link from "next/link";
import type { RetrievalCaseMetrics, SliceMetrics } from "@/lib/api";
import { EXPLAIN, pct } from "./constants";
import { Info } from "./metric-card";
import { MiniBar } from "./recall-curve";

// Coverage guidance: below ~25 measured queries, run-to-run metric deltas are mostly noise;
// 50+ gives trustworthy comparisons. Silent at >=50 to avoid clutter.
export function ReliabilityBanner({ count, source }: { count: number; source: "urls" | "labels" }) {
  if (count >= 50) return null;
  const noun = source === "labels" ? "labeled" : "measured";
  const strong = count < 25;
  return (
    <div
      className={`mb-4 flex items-start gap-2 rounded-lg border px-3 py-2 text-[12px] ${
        strong
          ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
          : "border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-900/60 text-gray-500 dark:text-slate-400"
      }`}
    >
      <span className="shrink-0">{strong ? "⚠" : "ℹ"}</span>
      <span>
        {strong ? (
          <>
            Only <span className="font-semibold tabular-nums">{count}</span> {noun}{" "}
            {count === 1 ? "query" : "queries"} — below 25, differences between runs are mostly
            noise. Aim for <span className="font-semibold">50+</span> for trustworthy
            comparisons.
          </>
        ) : (
          <>
            <span className="font-semibold tabular-nums">{count}</span> {noun} queries.{" "}
            <span className="font-semibold">50+</span> gives the most reliable run-to-run
            comparisons.
          </>
        )}
      </span>
    </div>
  );
}

const SLICE_BADGE: Record<string, string> = {
  safety: "bg-red-500/10 text-red-600 dark:text-red-300",
  adversarial: "bg-orange-500/10 text-orange-600 dark:text-orange-300",
  broad: "bg-slate-500/10 text-slate-600 dark:text-slate-300",
};

// Per-slice metric breakdown — a deep-rank miss on the safety slice shouldn't be averaged
// away by the broad slice, so each risk slice is reported on its own row.
export function SliceBreakdown({ slices, largestK }: { slices: SliceMetrics[]; largestK: number }) {
  const lk = String(largestK);
  return (
    <div className="mb-4 rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="px-4 pt-4 pb-2 text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500">
        By risk slice
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-gray-400 dark:text-slate-500 border-b border-gray-100 dark:border-slate-800">
            <tr>
              <th className="text-left font-medium px-4 py-2">Slice</th>
              <th className="text-right font-medium px-3 py-2">Cases</th>
              <th className="text-right font-medium px-3 py-2">Recall@{largestK}</th>
              <th className="text-right font-medium px-3 py-2">nDCG@{largestK}</th>
              <th className="text-right font-medium px-4 py-2">
                <span className="inline-flex items-center">bpref<Info text={EXPLAIN.bpref} /></span>
              </th>
            </tr>
          </thead>
          <tbody>
            {slices.map((s) => (
              <tr key={s.slice} className="border-b border-gray-50 dark:border-slate-800/50">
                <td className="px-4 py-2.5">
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide capitalize ${
                      SLICE_BADGE[s.slice] ?? SLICE_BADGE.broad
                    }`}
                  >
                    {s.slice}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-right font-mono tabular-nums text-gray-500 dark:text-slate-400">{s.case_count}</td>
                <td className="px-3 py-2.5 text-right font-mono tabular-nums text-gray-700 dark:text-slate-300">{pct(s.recall_at_k[lk])}</td>
                <td className="px-3 py-2.5 text-right font-mono tabular-nums text-gray-700 dark:text-slate-300">{pct(s.ndcg_at_k[lk])}</td>
                <td className="px-4 py-2.5 text-right font-mono tabular-nums text-gray-700 dark:text-slate-300">{s.bpref == null ? "-" : pct(s.bpref)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function PerCaseResults({
  cases,
  largestK,
  lk,
  metricLabel = "Recall",
  perCase = (c) => c.recall_at_k,
  metricTarget,
}: {
  cases: RetrievalCaseMetrics[];
  largestK: number;
  lk: string;
  // Which per-k metric the column shows (defaults to recall).
  metricLabel?: string;
  perCase?: (c: RetrievalCaseMetrics) => Record<string, number>;
  metricTarget: number | null;
}) {
  return (
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
                <span className="inline-flex items-center">{metricLabel}@{largestK}<Info text={EXPLAIN.caseRecall} /></span>
              </th>
              <th className="text-right font-medium px-2 py-2">
                <span className="inline-flex items-center">1st hit<Info text={EXPLAIN.firstHit} /></span>
              </th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr
                key={c.test_id}
                className="border-b border-gray-50 dark:border-slate-800/50 hover:bg-gray-50/60 dark:hover:bg-slate-800/30"
              >
                <td className="px-4 py-2.5 max-w-[280px]">
                  <div className="flex items-center gap-2">
                    <span
                      className={`shrink-0 w-1.5 h-1.5 rounded-full ${c.hit ? "bg-emerald-500" : "bg-red-500"}`}
                    />
                    {c.dataset_id ? (
                      <Link
                        href={`/datasets/${c.dataset_id}?highlight=${encodeURIComponent(c.test_id)}`}
                        className="truncate text-indigo-600 dark:text-indigo-400 hover:underline"
                        title={`Open test case: ${c.input ?? c.test_id}`}
                      >
                        {c.input || c.test_id}
                      </Link>
                    ) : (
                      <span className="truncate text-gray-700 dark:text-slate-300" title={c.input ?? c.test_id}>
                        {c.input || c.test_id}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-2 py-2.5 text-right font-mono tabular-nums text-gray-500 dark:text-slate-400">{c.expected_count}</td>
                <td className="px-2 py-2.5 text-right font-mono tabular-nums text-gray-500 dark:text-slate-400">{c.retrieved_count}</td>
                <td className="px-3 py-2.5">
                  <MiniBar
                    v={perCase(c)[lk] ?? 0}
                    ok={metricTarget != null ? (perCase(c)[lk] ?? 0) >= metricTarget : c.hit}
                  />
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
  );
}
