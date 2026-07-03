"use client";

import { useMemo, useState, type ReactNode } from "react";
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

type SortKey = "query" | "relevant" | "detail" | "metric" | "firsthit";

// Direction a column jumps to on its first click. Metric defaults ascending so the worst cases
// surface first (the old fixed "sorted by worst recall" behaviour, now applied to whichever metric
// is selected); count columns default to highest-first, which is the more useful first look.
const INITIAL_DIR: Record<SortKey, "asc" | "desc"> = {
  query: "asc",
  relevant: "desc",
  detail: "desc",
  metric: "asc",
  firsthit: "asc",
};

// A clickable column header that sorts by `sortKey` and shows the active direction arrow.
function SortTh({
  children,
  sortKey,
  sort,
  onSort,
  info,
  align = "right",
  className = "",
}: {
  children: ReactNode;
  sortKey: SortKey;
  sort: { key: SortKey; dir: "asc" | "desc" };
  onSort: (k: SortKey) => void;
  info?: string;
  align?: "left" | "right";
  className?: string;
}) {
  const active = sort.key === sortKey;
  return (
    <th className={`font-medium ${align === "left" ? "text-left" : "text-right"} ${className}`}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-0.5 cursor-pointer select-none hover:text-gray-600 dark:hover:text-slate-300 ${
          active ? "text-gray-600 dark:text-slate-300" : ""
        }`}
      >
        <span className="inline-flex items-center">
          {children}
          {info ? <Info text={info} /> : null}
        </span>
        <span className="w-2 text-[9px] leading-none">{active ? (sort.dir === "asc" ? "▲" : "▼") : ""}</span>
      </button>
    </th>
  );
}

export function PerCaseResults({
  cases,
  largestK,
  lk,
  metricLabel = "Recall",
  perCase = (c) => c.recall_at_k,
  metricTarget,
  metricInfo = EXPLAIN.caseRecall,
  ratio = (c) => {
    const num = c.relevant_retrieved_at_k?.[lk];
    const den = c.relevant_count ?? c.expected_count;
    return num == null || !den ? null : { num, den };
  },
  ratioHeader = "Found / Exp",
  ratioInfo = EXPLAIN.ratioRecall,
}: {
  cases: RetrievalCaseMetrics[];
  largestK: number;
  lk: string;
  // Which per-k metric the column shows (defaults to recall).
  metricLabel?: string;
  perCase?: (c: RetrievalCaseMetrics) => Record<string, number>;
  metricTarget: number | null;
  // Tooltip for the metric column header.
  metricInfo?: string;
  // The numerator/denominator behind the selected metric's percentage, shown as "num / den" so the
  // reader can see how the % is derived. `null` hides the whole column — used for nDCG/hit-rate,
  // whose per-case score isn't a plain fraction.
  ratio?: ((c: RetrievalCaseMetrics) => { num: number; den: number } | null) | null;
  ratioHeader?: string;
  ratioInfo?: string;
}) {
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "metric", dir: "asc" });
  const onSort = (k: SortKey) =>
    setSort((s) => (s.key === k ? { key: k, dir: s.dir === "asc" ? "desc" : "asc" } : { key: k, dir: INITIAL_DIR[k] }));

  // If the detail column is hidden (nDCG/hit-rate) but it was the active sort, fall back to metric.
  const key: SortKey = sort.key === "detail" && !ratio ? "metric" : sort.key;

  const sorted = useMemo(() => {
    const arr = [...cases];
    const mul = sort.dir === "asc" ? 1 : -1;
    const valOf = (c: RetrievalCaseMetrics): string | number => {
      switch (key) {
        case "query":
          return (c.input || c.test_id || "").toLowerCase();
        case "relevant":
          return c.expected_count ?? 0;
        case "detail":
          return ratio?.(c)?.num ?? -1;
        case "firsthit":
          return c.first_relevant_rank ?? Number.POSITIVE_INFINITY;
        default:
          return perCase(c)[lk] ?? 0;
      }
    };
    arr.sort((a, b) => {
      // "No first hit" always sorts to the bottom, whichever direction is active.
      if (key === "firsthit") {
        const ra = a.first_relevant_rank;
        const rb = b.first_relevant_rank;
        if (ra == null && rb == null) return 0;
        if (ra == null) return 1;
        if (rb == null) return -1;
        return (ra - rb) * mul;
      }
      const va = valOf(a);
      const vb = valOf(b);
      if (typeof va === "string" || typeof vb === "string") return String(va).localeCompare(String(vb)) * mul;
      return (va - vb) * mul;
    });
    return arr;
  }, [cases, key, sort.dir, perCase, ratio, lk]);

  return (
    <div className="lg:col-span-2 flex flex-col rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="flex items-center justify-between px-4 pt-4 pb-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500">
          Per-case results
        </span>
        <span className="text-[11px] text-gray-400 dark:text-slate-500">click a column to sort</span>
      </div>
      <div className="overflow-y-auto flex-1 max-h-[360px]">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-white dark:bg-slate-900 text-gray-400 dark:text-slate-500 border-b border-gray-100 dark:border-slate-800">
            <tr>
              <SortTh sortKey="query" sort={sort} onSort={onSort} align="left" className="px-4 py-2">
                Query
              </SortTh>
              <SortTh sortKey="relevant" sort={sort} onSort={onSort} info={EXPLAIN.expected} className="px-2 py-2 whitespace-nowrap">
                Relevant
              </SortTh>
              {ratio && (
                <SortTh sortKey="detail" sort={sort} onSort={onSort} info={ratioInfo} className="px-2 py-2 whitespace-nowrap">
                  {ratioHeader}
                </SortTh>
              )}
              <SortTh sortKey="metric" sort={sort} onSort={onSort} info={metricInfo} className="px-3 py-2 whitespace-nowrap">
                {metricLabel}@{largestK}
              </SortTh>
              <SortTh sortKey="firsthit" sort={sort} onSort={onSort} info={EXPLAIN.firstHit} className="px-2 py-2 whitespace-nowrap">
                1st hit
              </SortTh>
            </tr>
          </thead>
          <tbody>
            {sorted.map((c) => (
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
                        target="_blank"
                        rel="noopener noreferrer"
                        className="truncate text-indigo-600 dark:text-indigo-400 hover:underline"
                        title={`Open test case in a new tab: ${c.input ?? c.test_id}`}
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
                {ratio && (
                  <td className="px-2 py-2.5 text-right font-mono tabular-nums text-gray-500 dark:text-slate-400">
                    {(() => {
                      const r = ratio(c);
                      return r ? `${r.num} / ${r.den}` : "-";
                    })()}
                  </td>
                )}
                <td className="px-3 py-2.5">
                  <div className="flex items-center justify-end">
                    <MiniBar
                      v={perCase(c)[lk] ?? 0}
                      ok={metricTarget != null ? (perCase(c)[lk] ?? 0) >= metricTarget : c.hit}
                    />
                  </div>
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
