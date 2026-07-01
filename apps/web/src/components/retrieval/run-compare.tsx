"use client";

import { useMemo } from "react";
import { type RetrievalRunRecord } from "@/lib/api";
import { pct, dec } from "@/components/retrieval/constants";

// Side-by-side comparison of saved runs: a metric × run grid with best-per-row highlighting.
// Runs may carry different k-sets (e.g. an older @10 run vs a newer @20 one), so recall/nDCG/etc.
// rows are emitted only for the k's the selected runs share; single-value metrics (MRR, bpref)
// always show.
export function RunCompare({ runs }: { runs: RetrievalRunRecord[] }) {
  const sharedKs = useMemo(() => {
    if (!runs.length) return [] as number[];
    const sets = runs.map((r) => new Set(r.ks ?? []));
    return [...sets[0]].filter((k) => sets.every((s) => s.has(k))).sort((a, b) => a - b);
  }, [runs]);

  if (runs.length < 2) {
    return (
      <div className="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 text-center text-sm text-gray-500 dark:text-slate-400">
        Select at least two runs to compare.
      </div>
    );
  }

  type Row = { label: string; fmt: (v: number | null | undefined) => string; get: (r: RetrievalRunRecord) => number | null | undefined };
  const rows: Row[] = [];
  for (const k of sharedKs) {
    const kk = String(k);
    rows.push({ label: `Recall@${k}`, fmt: pct, get: (r) => r.metrics.recall_at_k?.[kk] });
    rows.push({ label: `nDCG@${k}`, fmt: pct, get: (r) => r.metrics.ndcg_at_k?.[kk] });
    rows.push({ label: `Precision@${k}`, fmt: pct, get: (r) => r.metrics.precision_at_k?.[kk] });
    rows.push({ label: `Hit@${k}`, fmt: pct, get: (r) => r.metrics.hit_rate_at_k?.[kk] });
  }
  rows.push({ label: "MRR", fmt: dec, get: (r) => r.metrics.mrr });
  rows.push({ label: "bpref", fmt: pct, get: (r) => r.metrics.bpref });

  const bestOf = (row: Row): number => {
    let best = -Infinity;
    for (const r of runs) {
      const v = row.get(r);
      if (typeof v === "number" && v > best) best = v;
    }
    return best;
  };

  const runLabel = (r: RetrievalRunRecord) =>
    r.name || (r.dataset_names.length === 1 ? r.dataset_names[0] : `${r.dataset_names.length} datasets`);

  return (
    <div className="rounded-xl border border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
            <th className="px-4 py-3 font-medium sticky left-0 bg-white dark:bg-slate-900 z-10">Metric</th>
            {runs.map((r) => (
              <th key={r.id} className="px-4 py-3 font-medium text-right align-bottom min-w-[140px]">
                <div className="text-gray-900 dark:text-white truncate max-w-[180px] ml-auto">{runLabel(r)}</div>
                <div className="text-[11px] font-normal text-gray-400 dark:text-slate-500">
                  {new Date(r.created_at).toLocaleDateString()}
                </div>
                {(r.pipeline_version || r.index_name) && (
                  <div className="text-[11px] font-normal text-gray-400 dark:text-slate-500 truncate max-w-[180px] ml-auto">
                    {[r.pipeline_version, r.index_name && `${r.index_name}${r.index_version ? ` ${r.index_version}` : ""}`]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const best = bestOf(row);
            return (
              <tr key={row.label} className="border-b border-gray-100/50 dark:border-slate-800/50">
                <td className="px-4 py-2.5 font-medium text-gray-700 dark:text-slate-300 sticky left-0 bg-white dark:bg-slate-900">
                  {row.label}
                </td>
                {runs.map((r) => {
                  const v = row.get(r);
                  const isBest = typeof v === "number" && v === best && runs.length > 1;
                  return (
                    <td
                      key={r.id}
                      className={`px-4 py-2.5 text-right tabular-nums ${
                        isBest
                          ? "font-semibold text-emerald-600 dark:text-emerald-400"
                          : "text-gray-700 dark:text-slate-300"
                      }`}
                    >
                      {row.fmt(v)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      {sharedKs.length === 0 && (
        <p className="px-4 py-3 text-xs text-amber-600 dark:text-amber-400">
          These runs share no common k, so only MRR and bpref are directly comparable.
        </p>
      )}
    </div>
  );
}
